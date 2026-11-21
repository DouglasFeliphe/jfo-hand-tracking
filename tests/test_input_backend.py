from __future__ import annotations

import pytest

from adapter.input_backend import SCANCODES, DryRunBackend, KeyboardBackend

BINDINGS = {"FORCE_PUSH": {"keys": ["2"], "hold_ms": 10}}


class RecordingBackend(KeyboardBackend):
    """KeyboardBackend sem chamadas ao Windows: foco e teclas são simulados."""

    def __init__(self, title: str = "STAR WARS Jedi: Fallen Order", fail_on: str | None = None,
                 bindings: dict | None = None, min_interval: float = 0.5) -> None:
        super().__init__(bindings or BINDINGS, "Jedi", min_interval=min_interval, user32=object())
        self.title = title
        self.fail_on = fail_on
        self.events: list[tuple[str, str]] = []

    def _foreground_title(self) -> str:
        return self.title

    def _key(self, name: str, up: bool) -> None:
        if self.fail_on == name and not up:
            raise OSError("SendInput falhou")
        self.events.append((name, "up" if up else "down"))


def test_key_two_uses_top_row_scancode() -> None:
    assert SCANCODES["2"] == 0x03


def test_injects_key_when_game_is_focused() -> None:
    backend = RecordingBackend()
    status, _ = backend.execute("FORCE_PUSH")
    assert status == "injected"
    assert backend.events == [("2", "down"), ("2", "up")]


def test_blocks_when_window_not_focused() -> None:
    backend = RecordingBackend(title="Mozilla Firefox")
    status, _ = backend.execute("FORCE_PUSH")
    assert status == "blocked_not_focused"
    assert backend.events == []


def test_rate_limit_between_commands() -> None:
    backend = RecordingBackend(min_interval=60.0)
    assert backend.execute("FORCE_PUSH")[0] == "injected"
    assert backend.execute("FORCE_PUSH")[0] == "rate_limited"
    assert backend.events == [("2", "down"), ("2", "up")]


def test_unknown_ability_fails_without_keys() -> None:
    backend = RecordingBackend()
    assert backend.execute("FORCE_PULL")[0] == "failed"
    assert backend.events == []


def test_releases_already_pressed_keys_on_failure() -> None:
    bindings = {"FORCE_PUSH": {"keys": ["LSHIFT", "2"], "hold_ms": 10}}
    backend = RecordingBackend(fail_on="2", bindings=bindings)
    status, _ = backend.execute("FORCE_PUSH")
    assert status == "failed"
    assert backend.events == [("LSHIFT", "down"), ("LSHIFT", "up")]


def test_invalid_bindings_are_rejected_at_startup() -> None:
    with pytest.raises(ValueError):
        KeyboardBackend({"FORCE_PUSH": {"keys": ["NOPE"]}}, "Jedi", user32=object())
    with pytest.raises(ValueError):
        KeyboardBackend({"FORCE_PUSH": {"keys": []}}, "Jedi", user32=object())
    with pytest.raises(ValueError):
        KeyboardBackend({"FORCE_PUSH": {"keys": ["2"], "hold_ms": 5000}}, "Jedi", user32=object())


def test_dry_run_sends_nothing() -> None:
    status, _ = DryRunBackend().execute("FORCE_PUSH")
    assert status == "dry_run"
