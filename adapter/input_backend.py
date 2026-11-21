from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Any, Protocol

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
    def execute(self, ability: str) -> tuple[str, str]:
        """Executa a habilidade e devolve (status, mensagem)."""
        ...


class DryRunBackend:
    """Não toca no sistema operacional; apenas confirma o recebimento."""

    def execute(self, ability: str) -> tuple[str, str]:
        return "dry_run", f"{ability} recebido; nenhuma tecla enviada (dry_run)."


class KeyboardBackend:
    """Injeta teclas via SendInput (scancodes) somente com o jogo em primeiro plano."""

    def __init__(
        self,
        bindings: dict[str, dict[str, Any]],
        window_title_contains: str,
        min_interval: float = 0.5,
        user32: Any | None = None,
    ) -> None:
        if not window_title_contains:
            raise ValueError("window_title_contains não pode ser vazio.")
        self._bindings: dict[str, tuple[tuple[str, ...], float]] = {}
        for ability, binding in bindings.items():
            keys = tuple(str(key).upper() for key in binding.get("keys", []))
            if not keys:
                raise ValueError(f"Binding de {ability} sem teclas.")
            unknown = [key for key in keys if key not in SCANCODES]
            if unknown:
                raise ValueError(f"Tecla(s) desconhecida(s) em {ability}: {', '.join(unknown)}")
            hold_ms = float(binding.get("hold_ms", 60))
            if not 10 <= hold_ms <= 1000:
                raise ValueError("hold_ms deve ficar entre 10 e 1000.")
            self._bindings[ability] = (keys, hold_ms / 1000.0)

        self.title_filter = window_title_contains.lower()
        self.min_interval = float(min_interval)
        self._last = 0.0
        self._lock = threading.Lock()

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

    def execute(self, ability: str) -> tuple[str, str]:
        binding = self._bindings.get(ability)
        if binding is None:
            return "failed", f"Sem binding para {ability}."
        keys, hold_seconds = binding

        if self.title_filter not in self._foreground_title().lower():
            return "blocked_not_focused", "Janela do jogo não está em primeiro plano."

        with self._lock:
            if time.monotonic() - self._last < self.min_interval:
                return "rate_limited", "Intervalo mínimo entre comandos não respeitado."
            pressed: list[str] = []
            try:
                for key in keys:
                    self._key(key, up=False)
                    pressed.append(key)
                time.sleep(hold_seconds)
            except OSError as error:
                return "failed", str(error)
            finally:
                for key in reversed(pressed):  # sempre solta o que foi pressionado
                    try:
                        self._key(key, up=True)
                    except OSError:
                        pass
            self._last = time.monotonic()
        return "injected", f"{ability} enviado ao jogo."
