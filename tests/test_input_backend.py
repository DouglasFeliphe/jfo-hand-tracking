from __future__ import annotations

import pytest

from adapter.input_backend import SCANCODES, DryRunBackend, KeyboardBackend

HOLD = {"FORCE_PUSH": {"keys": ["2"], "hold_ms": 80, "allow_hold": True}}
TAP = {"FORCE_PUSH": {"keys": ["2"], "hold_ms": 80, "allow_hold": False}}


class FakeKeyboard(KeyboardBackend):
    """KeyboardBackend sem Windows: foco, teclas e relógio são simulados."""

    def __init__(self, bindings=None, title: str = "STAR WARS Jedi: Fallen Order",
                 fail_on: str | None = None, **kwargs) -> None:
        self.t = 100.0
        self.title = title
        self.fail_on = fail_on
        self.events: list[tuple[str, str]] = []
        super().__init__(bindings or HOLD, "Jedi", user32=object(), clock=lambda: self.t,
                         start_watchdog=False, **kwargs)

    def _foreground_title(self) -> str:
        return self.title

    def _key(self, name: str, up: bool) -> None:
        if self.fail_on == name and not up:
            raise OSError("SendInput falhou")
        self.events.append((name, "up" if up else "down"))

    def advance(self, seconds: float) -> None:
        self.t += seconds
        self._tick()


def test_key_two_uses_top_row_scancode() -> None:
    assert SCANCODES["2"] == 0x03


def test_press_keeps_key_down_until_release() -> None:
    backend = FakeKeyboard()
    assert backend.press("FORCE_PUSH")[0] == "injected"
    for _ in range(10):  # 3 s segurando, com heartbeats a cada 0.3 s
        backend.advance(0.3)
        assert backend.heartbeat("FORCE_PUSH")[0] == "held"
    assert backend.events == [("2", "down")]  # ainda pressionada
    assert backend.release("FORCE_PUSH")[0] == "released"
    assert backend.events == [("2", "down"), ("2", "up")]


def test_quick_release_respects_minimum_hold() -> None:
    backend = FakeKeyboard()
    backend.press("FORCE_PUSH")
    backend.advance(0.02)
    backend.release("FORCE_PUSH")
    assert backend.events == [("2", "down")]  # ainda dentro do hold_ms
    backend.advance(0.05)
    assert backend.events == [("2", "down")]
    backend.advance(0.02)  # 0.09 s > 0.08 s
    assert backend.events == [("2", "down"), ("2", "up")]


def test_tap_ability_releases_itself() -> None:
    backend = FakeKeyboard(TAP)
    backend.press("FORCE_PUSH")
    backend.advance(0.05)
    assert backend.events == [("2", "down")]
    backend.advance(0.05)
    assert backend.events == [("2", "down"), ("2", "up")]


def test_watchdog_releases_without_heartbeat() -> None:
    backend = FakeKeyboard()
    backend.press("FORCE_PUSH")
    backend.advance(0.4)
    assert backend.heartbeat("FORCE_PUSH")[0] == "held"
    backend.advance(0.4)  # 0.4 s desde o último heartbeat: ainda vivo
    assert backend.events == [("2", "down")]
    backend.advance(0.2)  # 0.6 s sem heartbeat > 0.5 s
    assert backend.events == [("2", "down"), ("2", "up")]
    assert backend.heartbeat("FORCE_PUSH")[0] == "not_active"


def test_max_hold_caps_even_with_heartbeats() -> None:
    backend = FakeKeyboard(max_hold_seconds=1.0)
    backend.press("FORCE_PUSH")
    for _ in range(9):
        backend.advance(0.1)
        backend.heartbeat("FORCE_PUSH")
    assert backend.events == [("2", "down")]
    backend.advance(0.2)
    assert backend.events == [("2", "down"), ("2", "up")]


def test_focus_loss_releases_key() -> None:
    backend = FakeKeyboard()
    backend.press("FORCE_PUSH")
    backend.title = "Mozilla Firefox"
    backend.advance(0.05)
    assert backend.events == [("2", "down"), ("2", "up")]


def test_blocks_when_window_not_focused() -> None:
    backend = FakeKeyboard(title="Mozilla Firefox")
    assert backend.press("FORCE_PUSH")[0] == "blocked_not_focused"
    assert backend.events == []


def test_rate_limit_and_already_active() -> None:
    backend = FakeKeyboard()
    backend.press("FORCE_PUSH")
    assert backend.press("FORCE_PUSH")[0] == "already_active"
    backend.release("FORCE_PUSH")
    backend.advance(0.1)  # solta
    assert backend.press("FORCE_PUSH")[0] == "rate_limited"  # < 0.5 s desde o último press
    backend.advance(0.5)
    assert backend.press("FORCE_PUSH")[0] == "injected"


def test_unknown_ability_fails_without_keys() -> None:
    backend = FakeKeyboard()
    assert backend.press("FORCE_PULL")[0] == "failed"
    assert backend.events == []


def test_partial_press_failure_releases_pressed_keys() -> None:
    bindings = {"FORCE_PUSH": {"keys": ["LSHIFT", "2"], "hold_ms": 80, "allow_hold": True}}
    backend = FakeKeyboard(bindings, fail_on="2")
    assert backend.press("FORCE_PUSH")[0] == "failed"
    assert backend.events == [("LSHIFT", "down"), ("LSHIFT", "up")]
    assert backend.heartbeat("FORCE_PUSH")[0] == "not_active"


def test_close_releases_everything() -> None:
    bindings = {
        "FORCE_PUSH": {"keys": ["2"], "hold_ms": 80, "allow_hold": True},
        "FORCE_SLOW": {"keys": ["1"], "hold_ms": 80, "allow_hold": True},
    }
    backend = FakeKeyboard(bindings)
    backend.press("FORCE_PUSH")
    backend.press("FORCE_SLOW")
    backend.close()
    assert ("2", "up") in backend.events and ("1", "up") in backend.events


def test_invalid_bindings_are_rejected_at_startup() -> None:
    def make(bindings):
        return KeyboardBackend(bindings, "Jedi", user32=object(), start_watchdog=False)

    with pytest.raises(ValueError):
        make({"FORCE_PUSH": {"keys": ["NOPE"]}})
    with pytest.raises(ValueError):
        make({"FORCE_PUSH": {"keys": []}})
    with pytest.raises(ValueError):
        make({"FORCE_PUSH": {"keys": ["2"], "hold_ms": 5000}})
    with pytest.raises(ValueError):  # a mesma tecla em duas habilidades
        make({"FORCE_PUSH": {"keys": ["2"]}, "FORCE_PULL": {"keys": ["2"]}})


def test_dry_run_mimics_statuses() -> None:
    backend = DryRunBackend()
    assert backend.heartbeat("FORCE_PUSH")[0] == "not_active"
    assert backend.press("FORCE_PUSH")[0] == "dry_run"
    assert backend.heartbeat("FORCE_PUSH")[0] == "held"
    assert backend.release("FORCE_PUSH")[0] == "released"
    assert backend.release("FORCE_PUSH")[0] == "not_active"
