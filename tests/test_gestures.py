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
    assert next_frame.state == "COOLDOWN"
