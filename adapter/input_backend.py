from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Callable, Protocol

# Scancodes (set 1) da linha principal do teclado. A tecla "2" do topo é 0x03.
SCANCODES: dict[str, int] = {
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "Q": 0x10, "W": 0x11, "E": 0x12, "R": 0x13, "T": 0x14,
    "F": 0x21, "G": 0x22,
    "LSHIFT": 0x2A, "LCTRL": 0x1D, "SPACE": 0x39,
}

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):  # necessário para o tamanho correto da union
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _InputUnion)]


class InputBackend(Protocol):
    """Contrato dos backends. Cada método devolve (status, mensagem)."""

    def press(self, ability: str) -> tuple[str, str]: ...
    def release(self, ability: str) -> tuple[str, str]: ...
    def heartbeat(self, ability: str) -> tuple[str, str]: ...
    def close(self) -> None: ...


class DryRunBackend:
    """Não toca no sistema operacional; apenas imita os status do backend real."""

    def __init__(self) -> None:
        self._active: set[str] = set()
        self._lock = threading.Lock()

    def press(self, ability: str) -> tuple[str, str]:
        with self._lock:
            self._active.add(ability)
        return "dry_run", f"{ability} recebido; nenhuma tecla enviada (dry_run)."

    def release(self, ability: str) -> tuple[str, str]:
        with self._lock:
            was_active = ability in self._active
            self._active.discard(ability)
        if was_active:
            return "released", f"{ability} solto (dry_run)."
        return "not_active", f"{ability} não estava ativo."

    def heartbeat(self, ability: str) -> tuple[str, str]:
        with self._lock:
            active = ability in self._active
        return ("held", f"{ability} ativo (dry_run).") if active else ("not_active", f"{ability} não está ativo.")

    def close(self) -> None:
        with self._lock:
            self._active.clear()


@dataclass
class _Binding:
    keys: tuple[str, ...]
    hold_seconds: float   # tempo mínimo com a tecla pressionada (e total, se não permitir hold)
    allow_hold: bool      # True: a tecla fica pressionada até STOP; False: solta sozinha após hold_seconds


@dataclass
class _Active:
    binding: _Binding
    pressed_at: float
    last_beat: float
    min_release_at: float
    release_at: float | None


class KeyboardBackend:
    """Injeta teclas via SendInput (scancodes) somente com o jogo em primeiro plano.

    Proteções contra tecla presa (watchdog, a cada `poll_interval`):
    - sem heartbeat por `heartbeat_timeout` segundos (habilidades com hold);
    - janela do jogo perdeu o foco;
    - tempo total acima de `max_hold_seconds`;
    - encerramento do adaptador (`close`).
    """

    def __init__(
        self,
        bindings: dict[str, dict[str, Any]],
        window_title_contains: str,
        min_interval: float = 0.5,
        heartbeat_timeout: float = 0.5,
        max_hold_seconds: float = 8.0,
        user32: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        start_watchdog: bool = True,
        poll_interval: float = 0.02,
    ) -> None:
        if not window_title_contains:
            raise ValueError("window_title_contains não pode ser vazio.")
        if heartbeat_timeout <= 0 or max_hold_seconds <= 0:
            raise ValueError("heartbeat_timeout e max_hold_seconds devem ser positivos.")

        self._bindings: dict[str, _Binding] = {}
        used_keys: dict[str, str] = {}
        for ability, raw in bindings.items():
            keys = tuple(str(key).upper() for key in raw.get("keys", []))
            if not keys:
                raise ValueError(f"Binding de {ability} sem teclas.")
            unknown = [key for key in keys if key not in SCANCODES]
            if unknown:
                raise ValueError(f"Tecla(s) desconhecida(s) em {ability}: {', '.join(unknown)}")
            for key in keys:
                if key in used_keys and used_keys[key] != ability:
                    raise ValueError(f"A tecla {key} é usada por {used_keys[key]} e {ability}.")
                used_keys[key] = ability
            hold_ms = float(raw.get("hold_ms", 60))
            if not 10 <= hold_ms <= 1000:
                raise ValueError("hold_ms deve ficar entre 10 e 1000.")
            self._bindings[ability] = _Binding(keys, hold_ms / 1000.0, bool(raw.get("allow_hold", False)))

        self.title_filter = window_title_contains.lower()
        self.min_interval = float(min_interval)
        self.heartbeat_timeout = float(heartbeat_timeout)
        self.max_hold_seconds = float(max_hold_seconds)
        self._clock = clock
        self._lock = threading.RLock()
        self._active: dict[str, _Active] = {}
        self._last_press: dict[str, float] = {}

        if user32 is None:
            if not hasattr(ctypes, "windll"):
                raise RuntimeError("KeyboardBackend só funciona no Windows.")
            user32 = ctypes.windll.user32
            user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
            user32.SendInput.restype = wintypes.UINT
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
            user32.GetWindowTextW.restype = ctypes.c_int
        self._user32 = user32

        self._stop_event = threading.Event()
        self._poll_interval = poll_interval
        self._thread: threading.Thread | None = None
        if start_watchdog:
            self._thread = threading.Thread(target=self._watchdog, name="key-watchdog", daemon=True)
            self._thread.start()

    # --- Windows ---------------------------------------------------------
    def _foreground_title(self) -> str:
        hwnd = self._user32.GetForegroundWindow()
        buffer = ctypes.create_unicode_buffer(256)
        self._user32.GetWindowTextW(hwnd, buffer, 256)
        return buffer.value

    def _key(self, name: str, up: bool) -> None:
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
        event = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, SCANCODES[name], flags, 0, 0))
        sent = self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
        if sent != 1:
            raise OSError("SendInput falhou (o jogo está rodando como administrador?)")

    def _focused(self) -> bool:
        return self.title_filter in self._foreground_title().lower()

    # --- API do backend ----------------------------------------------------
    def press(self, ability: str) -> tuple[str, str]:
        binding = self._bindings.get(ability)
        if binding is None:
            return "failed", f"Sem binding para {ability}."
        if not self._focused():
            return "blocked_not_focused", "Janela do jogo não está em primeiro plano."

        with self._lock:
            now = self._clock()
            if ability in self._active:
                return "already_active", f"{ability} já está pressionado."
            last = self._last_press.get(ability)
            if last is not None and now - last < self.min_interval:
                return "rate_limited", "Intervalo mínimo entre comandos não respeitado."

            pressed: list[str] = []
            try:
                for key in binding.keys:
                    self._key(key, up=False)
                    pressed.append(key)
            except OSError as error:
                for key in reversed(pressed):
                    try:
                        self._key(key, up=True)
                    except OSError:
                        pass
                return "failed", str(error)

            self._last_press[ability] = now
            min_release = now + binding.hold_seconds
            self._active[ability] = _Active(
                binding=binding,
                pressed_at=now,
                last_beat=now,
                min_release_at=min_release,
                release_at=None if binding.allow_hold else min_release,
            )
        return "injected", f"{ability} pressionado."

    def release(self, ability: str) -> tuple[str, str]:
        with self._lock:
            state = self._active.get(ability)
            if state is None:
                return "not_active", f"{ability} não estava pressionado."
            now = self._clock()
            # Respeita o tempo mínimo: um toque rápido ainda vira um toque válido.
            state.release_at = max(now, state.min_release_at)
            if state.release_at <= now:
                self._release_locked(ability)
        return "released", f"{ability} solto."

    def heartbeat(self, ability: str) -> tuple[str, str]:
        with self._lock:
            state = self._active.get(ability)
            if state is None:
                return "not_active", f"{ability} não está pressionado (soltura automática?)."
            state.last_beat = self._clock()
        return "held", f"{ability} mantido."

    def release_all(self) -> None:
        with self._lock:
            for ability in list(self._active):
                self._release_locked(ability)

    def close(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self.release_all()

    # --- interno -------------------------------------------------------------
    def _release_locked(self, ability: str) -> None:
        state = self._active.pop(ability, None)
        if state is None:
            return
        for key in reversed(state.binding.keys):
            try:
                self._key(key, up=True)
            except OSError:
                pass

    def _tick(self, now: float | None = None) -> None:
        with self._lock:
            if not self._active:
                return
            now = self._clock() if now is None else now
            focused = self._focused()
            for ability, state in list(self._active.items()):
                if (
                    not focused
                    or (state.release_at is not None and now >= state.release_at)
                    or (state.binding.allow_hold and now - state.last_beat > self.heartbeat_timeout)
                    or now - state.pressed_at > self.max_hold_seconds
                ):
                    self._release_locked(ability)

    def _watchdog(self) -> None:
        while not self._stop_event.wait(self._poll_interval):
            try:
                self._tick()
            except Exception as error:  # o watchdog nunca pode morrer
                print(f"[ADAPTER] Erro no watchdog: {error}")
