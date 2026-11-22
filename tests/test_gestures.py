from types import SimpleNamespace

import pytest

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
            points[idx] = (x, y, z)
    # Open, separated thumb.
    points[1] = (0.39, 0.68, z)
    points[2] = (0.32, 0.72, z)
    points[3] = (0.27, 0.77, z)
    points[4] = (0.22, 0.82, z)
    # Escala uniforme em torno do centro da palma: todos os pontos crescem juntos, como numa mão real.
    points = [(0.5 + (x - 0.5) * scale, 0.5 + (y - 0.5) * scale, zz) for x, y, zz in points]
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


# --- Fase 5: critério de disparo mais robusto -------------------------------------------------

import random  # noqa: E402

FRAME = 1 / 30


def make_yaw_hand(yaw: float, z: float = 0.0):
    """Mão girada: só a largura muda (x escalado), como ao virar a palma para a câmera."""
    hand = make_hand(1.0, z)
    for point in hand.landmarks.landmark:
        point.x = 0.5 + (point.x - 0.5) * yaw
    return hand


class Clock:
    def __init__(self, recognizer: GestureRecognizer) -> None:
        self.recognizer = recognizer
        self.t = 1.0
        self.results = []

    def feed(self, hand) -> None:
        self.results.append(self.recognizer.update(hand, now=self.t))
        self.t += FRAME

    def hold(self, frames: int, scale: float = 1.0, z: float = 0.0) -> None:
        for _ in range(frames):
            self.feed(make_hand(scale=scale, z=z))

    def ramp(self, frames: int, start: float, end: float, z_per_scale: float = 0.15) -> None:
        for step in range(1, frames + 1):
            scale = start + (end - start) * step / frames
            self.feed(make_hand(scale=scale, z=-z_per_scale * (scale - 1.0)))

    @property
    def triggers(self) -> int:
        return sum(result.triggered for result in self.results)

    @property
    def releases(self) -> int:
        return sum(result.hold_released for result in self.results)


def fixed_recognizer(**overrides) -> GestureRecognizer:
    config = dict(arm_stability_seconds=0.1, scale_trigger_ratio=1.08, scale_strong_ratio=1.16,
                  z_trigger_delta=0.004, smoothing_samples=1, adaptive_threshold=False,
                  hold_release_seconds=0.1, cooldown_seconds=0.4)
    config.update(overrides)
    return GestureRecognizer(**config)


def test_slow_lean_toward_camera_does_not_trigger():
    clock = Clock(fixed_recognizer())
    clock.hold(15)
    clock.ramp(60, 1.0, 1.25)  # +25% em 2 s
    clock.hold(30, scale=1.25, z=-0.0375)
    assert clock.triggers == 0


def test_quick_push_triggers_even_after_a_slow_lean():
    clock = Clock(fixed_recognizer())
    clock.hold(15)
    clock.ramp(60, 1.0, 1.25)
    clock.ramp(8, 1.25, 1.25 * 1.15)  # empurrão rápido: +15% em ~0,27 s
    assert clock.triggers == 1


def test_turning_the_hand_does_not_trigger_even_with_noisy_depth():
    clock = Clock(fixed_recognizer())
    clock.hold(15)
    for step in range(1, 13):
        yaw = 1.0 + 0.3 * step / 12
        clock.feed(make_yaw_hand(yaw, z=-0.02 * step / 12))  # z "ajudando", como no ruído real
    clock.hold(10)
    assert clock.triggers == 0


def test_anisotropy_is_reported_for_a_turning_hand_but_not_for_a_push():
    recognizer = fixed_recognizer(smoothing_samples=1)
    recognizer.update(make_hand(), now=1.0)
    rotated = recognizer.update(make_yaw_hand(1.3), now=1.0 + FRAME)
    assert rotated.anisotropy > 1.15
    recognizer = fixed_recognizer(smoothing_samples=1)
    recognizer.update(make_hand(), now=1.0)
    pushed = recognizer.update(make_hand(scale=1.3), now=1.0 + FRAME)
    assert pushed.anisotropy == pytest.approx(1.0, abs=1e-6)


def test_second_push_does_not_require_closing_the_fist():
    clock = Clock(fixed_recognizer())
    clock.hold(15)
    clock.ramp(8, 1.0, 1.15)
    clock.hold(9, scale=1.15, z=-0.0225)
    clock.ramp(8, 1.15, 1.0)  # recua com a palma aberta
    clock.hold(30)            # descansa 1 s com a mão aberta
    clock.ramp(8, 1.0, 1.15)
    assert clock.triggers == 2
    assert clock.releases >= 1


def test_without_rearm_on_retract_the_fist_is_still_required():
    clock = Clock(fixed_recognizer(rearm_on_retract=False))
    clock.hold(15)
    clock.ramp(8, 1.0, 1.15)
    clock.hold(9, scale=1.15, z=-0.0225)
    clock.ramp(8, 1.15, 1.0)
    clock.hold(60)
    clock.ramp(8, 1.0, 1.15)
    assert clock.triggers == 1


def test_hold_reference_is_the_scale_before_the_push_not_the_arming_scale():
    clock = Clock(fixed_recognizer())
    clock.hold(15)
    clock.ramp(60, 1.0, 1.20)             # inclinou-se devagar até 1,20
    clock.ramp(8, 1.20, 1.20 * 1.12)      # empurrão
    assert clock.triggers == 1
    clock.hold(6, scale=1.20 * 1.12, z=-0.03)
    assert clock.recognizer.state == "HOLDING"
    clock.hold(10, scale=1.20)            # volta ao nível de antes do empurrão
    assert clock.releases == 1


def test_noise_estimate_is_zero_for_a_clean_hand_and_needs_enough_samples():
    recognizer = GestureRecognizer(adaptive_threshold=True, scale_trigger_ratio=1.07, min_scale_trigger=1.06)
    clock = Clock(recognizer)
    clock.hold(10)
    assert recognizer.noise_sigma() is None
    assert recognizer.trigger_ratio() == pytest.approx(1.07)  # reserva: poucas amostras
    clock.hold(40)
    assert recognizer.noise_sigma() == pytest.approx(0.0, abs=1e-9)
    assert recognizer.trigger_ratio() == pytest.approx(1.06)  # piso


def test_trigger_threshold_rises_with_tracking_noise_up_to_the_cap():
    rng = random.Random(3)
    recognizer = GestureRecognizer(adaptive_threshold=True, noise_k=4.0, min_scale_trigger=1.06,
                                   max_scale_trigger=1.12, smoothing_samples=1)
    clock = Clock(recognizer)
    for _ in range(90):
        clock.feed(make_hand(scale=1.0 + rng.gauss(0, 0.02)))
    sigma = recognizer.noise_sigma()
    assert sigma is not None and 0.014 < sigma < 0.028
    assert 1.06 < recognizer.trigger_ratio() < 1.12  # acima do piso, abaixo do teto

    quiet = GestureRecognizer(adaptive_threshold=True, noise_k=4.0, min_scale_trigger=1.06,
                              max_scale_trigger=1.12, smoothing_samples=1)
    clock = Clock(quiet)
    for _ in range(90):
        clock.feed(make_hand(scale=1.0 + rng.gauss(0, 0.004)))
    assert quiet.trigger_ratio() == pytest.approx(1.06)  # ruído baixo: fica no piso

    noisy = GestureRecognizer(adaptive_threshold=True, noise_k=4.0, min_scale_trigger=1.06,
                              max_scale_trigger=1.12, smoothing_samples=1)
    clock = Clock(noisy)
    for _ in range(90):
        clock.feed(make_hand(scale=1.0 + rng.gauss(0, 0.05)))
    assert noisy.trigger_ratio() == pytest.approx(1.12)  # limitado pelo teto


def test_noise_estimate_ignores_the_push_itself():
    recognizer = GestureRecognizer(adaptive_threshold=True, smoothing_samples=1, arm_stability_seconds=0.1)
    clock = Clock(recognizer)
    clock.hold(40)
    clock.ramp(8, 1.0, 1.3)
    clock.hold(5, scale=1.3, z=-0.045)
    assert recognizer.noise_sigma() == pytest.approx(0.0, abs=1e-9)  # MAD ignora os poucos quadros do empurrão


def test_hand_lost_clears_noise_history():
    recognizer = GestureRecognizer(adaptive_threshold=True, smoothing_samples=1)
    clock = Clock(recognizer)
    clock.hold(40)
    assert recognizer.noise_sigma() is not None
    recognizer.update(None, now=clock.t)
    assert recognizer.noise_sigma() is None
