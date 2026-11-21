from __future__ import annotations

import pytest
from test_gestures import make_hand

from hand_tracking.gestures import GestureRecognizer
from hand_tracking.pinch import PinchRecognizer

PALM_WIDTH = 0.2518  # distância entre os pontos 5 e 17 de make_hand()


def make_pinch_hand(ratio: float = 0.10, curl: tuple[int, ...] = ()):
    """Mão com o polegar tocando o indicador (razão = distância / largura da palma).

    `curl` dobra os dedos indicados pelo índice do MCP (9 médio, 13 anelar, 17 mínimo).
    """
    hand = make_hand()
    points = hand.landmarks.landmark
    points[4].x = points[8].x + ratio * PALM_WIDTH
    points[4].y = points[8].y
    for mcp in curl:
        points[mcp + 3].x = points[mcp].x
        points[mcp + 3].y = points[mcp].y
    return hand


def make_recognizer(**overrides) -> PinchRecognizer:
    config = dict(stability_seconds=0.2, cooldown_seconds=0.4, hold_release_seconds=0.15,
                  hold_lost_grace_seconds=0.1)
    config.update(overrides)
    return PinchRecognizer(**config)


def trigger(recognizer: PinchRecognizer) -> None:
    assert recognizer.update(make_pinch_hand(), now=1.0).triggered is False
    assert recognizer.update(make_pinch_hand(), now=1.25).triggered is True
    assert recognizer.update(make_pinch_hand(), now=1.26).state == "HOLDING"


def test_stable_pinch_triggers_after_stability_interval():
    recognizer = make_recognizer()
    first = recognizer.update(make_pinch_hand(), now=1.0)
    assert first.state == "TRACKING"
    assert first.triggered is False
    second = recognizer.update(make_pinch_hand(), now=1.25)
    assert second.triggered is True
    assert second.state == "GESTURE_DETECTED"
    assert recognizer.holding is True


def test_trigger_happens_only_once():
    recognizer = make_recognizer()
    trigger(recognizer)
    for step in range(1, 8):
        result = recognizer.update(make_pinch_hand(), now=1.26 + step * 0.1)
        assert result.triggered is False
        assert result.state == "HOLDING"


def test_open_palm_never_triggers_slow():
    recognizer = make_recognizer()
    for step in range(20):
        assert recognizer.update(make_hand(), now=1.0 + step * 0.1).triggered is False


def test_pinch_never_arms_the_push_gesture():
    push = GestureRecognizer(arm_stability_seconds=0.1, smoothing_samples=1)
    for step in range(20):
        result = push.update(make_pinch_hand(), now=1.0 + step * 0.1)
        assert result.state == "TRACKING"
        assert result.open_palm is False


def test_push_exclusion_can_be_disabled():
    push = GestureRecognizer(arm_stability_seconds=0.1, smoothing_samples=1, pinch_exclusion_ratio=0.0)
    assert push.update(make_pinch_hand(), now=1.0).open_palm is True  # sem a proteção, a pinça "vira" palma


def test_curled_fingers_do_not_count_as_pinch():
    recognizer = make_recognizer()
    for step in range(10):
        result = recognizer.update(make_pinch_hand(curl=(9,)), now=1.0 + step * 0.1)
        assert result.triggered is False


def test_loose_pinch_between_thresholds_does_not_trigger():
    recognizer = make_recognizer()
    for step in range(10):
        assert recognizer.update(make_pinch_hand(ratio=0.35), now=1.0 + step * 0.1).triggered is False


def test_brief_flicker_does_not_trigger():
    recognizer = make_recognizer()
    recognizer.update(make_pinch_hand(), now=1.0)
    recognizer.update(make_hand(), now=1.1)  # pinça desfeita: o contador reinicia
    assert recognizer.update(make_pinch_hand(), now=1.2).triggered is False
    assert recognizer.update(make_pinch_hand(), now=1.3).triggered is False
    assert recognizer.update(make_pinch_hand(), now=1.45).triggered is True


def test_hold_survives_loose_pinch_hysteresis():
    recognizer = make_recognizer()
    trigger(recognizer)
    for step in range(1, 10):
        result = recognizer.update(make_pinch_hand(ratio=0.35), now=1.26 + step * 0.1)
        assert result.state == "HOLDING"
        assert result.hold_released is False


def test_hold_releases_once_when_pinch_opens():
    recognizer = make_recognizer()
    trigger(recognizer)
    first = recognizer.update(make_hand(), now=1.30)
    assert first.hold_released is False  # debounce
    still = recognizer.update(make_hand(), now=1.40)
    assert still.hold_released is False
    released = recognizer.update(make_hand(), now=1.50)
    assert released.hold_released is True
    assert released.state == "COOLDOWN"
    again = recognizer.update(make_hand(), now=1.60)
    assert again.hold_released is False
    assert recognizer.holding is False


def test_hold_releases_when_other_fingers_curl():
    recognizer = make_recognizer()
    trigger(recognizer)
    recognizer.update(make_pinch_hand(curl=(9, 13, 17)), now=1.30)
    released = recognizer.update(make_pinch_hand(curl=(9, 13, 17)), now=1.50)
    assert released.hold_released is True


def test_brief_noise_does_not_release_hold():
    recognizer = make_recognizer()
    trigger(recognizer)
    recognizer.update(make_hand(), now=1.30)  # um quadro ruim
    recovered = recognizer.update(make_pinch_hand(), now=1.33)
    assert recovered.state == "HOLDING"
    later = recognizer.update(make_hand(), now=1.50)
    assert later.hold_released is False  # o contador reiniciou


def test_hand_lost_releases_after_grace_period():
    recognizer = make_recognizer()
    trigger(recognizer)
    within_grace = recognizer.update(None, now=1.35)
    assert within_grace.state == "HOLDING"
    assert within_grace.hold_released is False
    released = recognizer.update(None, now=1.50)
    assert released.hold_released is True
    assert released.state == "HAND_LOST"


def test_hand_lost_without_hold_does_not_report_release():
    recognizer = make_recognizer()
    recognizer.update(make_pinch_hand(), now=1.0)
    lost = recognizer.update(None, now=1.1)
    assert lost.state == "HAND_LOST"
    assert lost.hold_released is False


def test_hold_disabled_releases_on_next_frame():
    recognizer = make_recognizer(hold_enabled=False)
    recognizer.update(make_pinch_hand(), now=1.0)
    assert recognizer.update(make_pinch_hand(), now=1.25).triggered is True
    follow_up = recognizer.update(make_pinch_hand(), now=1.26)
    assert follow_up.state == "COOLDOWN"
    assert follow_up.hold_released is True


def test_rearm_needs_cooldown_and_open_pinch():
    recognizer = make_recognizer()
    trigger(recognizer)  # disparo em 1.25
    recognizer.update(make_hand(), now=1.30)
    assert recognizer.update(make_hand(), now=1.50).hold_released is True
    assert recognizer.update(make_pinch_hand(), now=1.60).state == "COOLDOWN"  # cooldown não terminou
    assert recognizer.update(make_pinch_hand(), now=1.70).state == "COOLDOWN"  # ainda pinçando
    assert recognizer.update(make_hand(), now=1.75).state == "TRACKING"        # pinça desfeita
    recognizer.update(make_pinch_hand(), now=1.80)
    assert recognizer.update(make_pinch_hand(), now=2.05).triggered is True


def test_suppressed_blocks_trigger_until_it_ends():
    recognizer = make_recognizer()
    for now in (1.0, 1.3, 1.6):
        assert recognizer.update(make_pinch_hand(), now=now, suppressed=True).triggered is False
    assert recognizer.update(make_pinch_hand(), now=1.7).triggered is False  # contagem recomeça
    assert recognizer.update(make_pinch_hand(), now=1.8).triggered is False
    assert recognizer.update(make_pinch_hand(), now=1.95).triggered is True


def test_invalid_hysteresis_is_rejected():
    with pytest.raises(ValueError):
        PinchRecognizer(pinch_close_ratio=0.5, pinch_open_ratio=0.4)
