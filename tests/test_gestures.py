from types import SimpleNamespace

from hand_tracking.gestures import GestureRecognizer, _angle


def make_hand(scale: float = 1.0, z: float = 0.0):
    """Synthetic frontal open hand; normalized coordinates are sufficient for unit tests."""
    points = [(0.5, 0.8, z) for _ in range(21)]
    # Wrist and palm anchors.
    points[0] = (0.50, 0.82, z)
    points[5] = (0.40, 0.55, z)
    points[9] = (0.50, 0.50, z)
    points[13] = (0.58, 0.55, z)
    points[17] = (0.65, 0.58, z)
    # Straight fingers: MCP -> PIP -> TIP continue along a line.
    finger_data = {
        5: ((0.40, 0.55), (0.38, 0.40), (0.37, 0.25)),
        9: ((0.50, 0.50), (0.50, 0.32), (0.50, 0.14)),
        13: ((0.58, 0.55), (0.60, 0.39), (0.62, 0.24)),
        17: ((0.65, 0.58), (0.69, 0.45), (0.72, 0.32)),
    }
    for mcp, (a, b, c) in finger_data.items():
        pip = mcp + 1
        dip = mcp + 2
        tip = mcp + 3
        for idx, (x, y) in ((mcp, a), (pip, b), (dip, c), (tip, c)):
            points[idx] = (0.5 + (x - 0.5) * scale, 0.5 + (y - 0.5) * scale, z)
    # Open, separated thumb.
    points[1] = (0.39, 0.68, z)
    points[2] = (0.32, 0.72, z)
    points[3] = (0.27, 0.77, z)
    points[4] = (0.22, 0.82, z)
    points = [SimpleNamespace(x=x, y=y, z=zz) for x, y, zz in points]
    return SimpleNamespace(landmarks=SimpleNamespace(landmark=points))


def test_angle_straight_finger_is_180_degrees():
    assert _angle((0, 0), (1, 0), (2, 0)) == 180.0


def test_open_palm_arms_after_stability_interval():
    recognizer = GestureRecognizer(arm_stability_seconds=0.3)
    first = recognizer.update(make_hand(), now=1.0)
    second = recognizer.update(make_hand(), now=1.4)
    assert first.state == "TRACKING"
    assert second.state == "ARMED"


def test_forward_thrust_triggers_once():
    recognizer = GestureRecognizer(
        arm_stability_seconds=0.1,
        scale_trigger_ratio=1.10,
        scale_strong_ratio=1.20,
        z_trigger_delta=0.004,
        smoothing_samples=1,
    )
    recognizer.update(make_hand(), now=1.0)
    armed = recognizer.update(make_hand(), now=1.2)
    assert armed.state == "ARMED"
    pushed = recognizer.update(make_hand(scale=1.30, z=-0.02), now=1.3)
    assert pushed.triggered is True
    assert pushed.state == "GESTURE_DETECTED"
    next_frame = recognizer.update(make_hand(scale=1.30, z=-0.02), now=1.31)
    assert next_frame.triggered is False
    assert next_frame.state == "HOLDING"
    assert next_frame.hold_released is False


# --- Segurar (hold) -----------------------------------------------------------

def make_closed_hand(scale: float = 1.0, z: float = 0.0):
    """Mesma palma de make_hand, mas com as pontas dos dedos dobradas sobre a palma."""
    hand = make_hand(scale=scale, z=z)
    points = hand.landmarks.landmark
    for mcp in (5, 9, 13, 17):
        points[mcp + 3].x = points[mcp].x
        points[mcp + 3].y = points[mcp].y
    return hand


def make_recognizer(**overrides) -> GestureRecognizer:
    config = dict(
        arm_stability_seconds=0.1,
        scale_trigger_ratio=1.10,
        scale_strong_ratio=1.20,
        z_trigger_delta=0.004,
        smoothing_samples=1,
        hold_release_seconds=0.1,
        hold_lost_grace_seconds=0.1,
    )
    config.update(overrides)
    return GestureRecognizer(**config)


def push(recognizer: GestureRecognizer) -> None:
    recognizer.update(make_hand(), now=1.0)
    recognizer.update(make_hand(), now=1.2)
    assert recognizer.update(make_hand(scale=1.30, z=-0.02), now=1.3).triggered
    assert recognizer.update(make_hand(scale=1.30, z=-0.02), now=1.31).state == "HOLDING"


def test_hold_continues_while_palm_open_and_extended():
    recognizer = make_recognizer()
    push(recognizer)
    for step in range(1, 11):
        result = recognizer.update(make_hand(scale=1.30, z=-0.02), now=1.31 + step * 0.1)
        assert result.state == "HOLDING"
        assert result.hold_released is False
    assert recognizer.holding is True


def test_hold_releases_once_when_palm_closes():
    recognizer = make_recognizer()
    push(recognizer)
    first = recognizer.update(make_closed_hand(scale=1.30, z=-0.02), now=1.40)
    assert first.hold_released is False  # debounce: ainda dentro de hold_release_seconds
    released = recognizer.update(make_closed_hand(scale=1.30, z=-0.02), now=1.55)
    assert released.hold_released is True
    assert released.state == "COOLDOWN"
    again = recognizer.update(make_closed_hand(scale=1.30, z=-0.02), now=1.60)
    assert again.hold_released is False
    assert recognizer.holding is False


def test_hold_releases_when_hand_pulls_back():
    recognizer = make_recognizer()
    push(recognizer)
    recognizer.update(make_hand(scale=1.0, z=0.0), now=1.40)
    released = recognizer.update(make_hand(scale=1.0, z=0.0), now=1.55)
    assert released.hold_released is True


def test_brief_noise_does_not_release_hold():
    recognizer = make_recognizer()
    push(recognizer)
    recognizer.update(make_closed_hand(scale=1.30, z=-0.02), now=1.40)  # um frame ruim
    recovered = recognizer.update(make_hand(scale=1.30, z=-0.02), now=1.43)
    assert recovered.state == "HOLDING"
    later = recognizer.update(make_closed_hand(scale=1.30, z=-0.02), now=1.60)
    assert later.hold_released is False  # o contador de debounce reiniciou


def test_hand_lost_releases_after_grace_period():
    recognizer = make_recognizer()
    push(recognizer)
    within_grace = recognizer.update(None, now=1.40)
    assert within_grace.state == "HOLDING"
    assert within_grace.hold_released is False
    released = recognizer.update(None, now=1.55)
    assert released.hold_released is True
    assert released.state == "HAND_LOST"


def test_hand_returning_within_grace_keeps_holding():
    recognizer = make_recognizer()
    push(recognizer)
    recognizer.update(None, now=1.40)
    back = recognizer.update(make_hand(scale=1.30, z=-0.02), now=1.45)
    assert back.state == "HOLDING"
    assert back.hold_released is False
    late = recognizer.update(None, now=1.80)  # nova perda: a janela de tolerância reinicia
    assert late.hold_released is False


def test_hold_disabled_releases_on_next_frame():
    recognizer = make_recognizer(hold_enabled=False)
    recognizer.update(make_hand(), now=1.0)
    recognizer.update(make_hand(), now=1.2)
    assert recognizer.update(make_hand(scale=1.30, z=-0.02), now=1.3).triggered
    follow_up = recognizer.update(make_hand(scale=1.30, z=-0.02), now=1.31)
    assert follow_up.state == "COOLDOWN"
    assert follow_up.hold_released is True


def test_hand_lost_without_hold_does_not_report_release():
    recognizer = make_recognizer()
    recognizer.update(make_hand(), now=1.0)
    lost = recognizer.update(None, now=1.1)
    assert lost.state == "HAND_LOST"
    assert lost.hold_released is False
