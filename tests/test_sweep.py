from __future__ import annotations

import pytest
from test_gestures import make_hand

from hand_tracking.sweep import SweepRecognizer

DT = 1 / 30
PALM_SIZE = 0.286          # (largura + comprimento da palma de make_hand()) / 2
FAST = 5.0 * PALM_SIZE * DT   # 5 palmas/s por quadro, em unidades da imagem
SLOW_DRIFT = 1.0 * PALM_SIZE * DT


def make_moved_hand(dx: float = 0.0, dy: float = 0.0, closed: bool = False):
    hand = make_hand()
    points = hand.landmarks.landmark
    for point in points:
        point.x += dx
        point.y += dy
    if closed:
        for mcp in (5, 9, 13, 17):
            points[mcp + 3].x = points[mcp].x
            points[mcp + 3].y = points[mcp].y
    return hand


class Driver:
    """Alimenta o reconhecedor a 30 FPS com a mão em movimento."""

    def __init__(self, recognizer: SweepRecognizer) -> None:
        self.recognizer = recognizer
        self.t = 1.0
        self.x = 0.0
        self.y = 0.0
        self.results = []

    def step(self, dx: float = 0.0, dy: float = 0.0, closed: bool = False):
        self.x += dx
        self.y += dy
        self.t += DT
        result = self.recognizer.update(make_moved_hand(self.x, self.y, closed), now=self.t)
        self.results.append(result)
        return result

    def run(self, frames: int, dx: float = 0.0, dy: float = 0.0, closed: bool = False) -> None:
        for _ in range(frames):
            self.step(dx, dy, closed)

    def lose(self, seconds: float):
        self.t += seconds
        return self.recognizer.update(None, now=self.t)

    @property
    def triggers(self) -> int:
        return sum(result.triggered for result in self.results)

    @property
    def releases(self) -> int:
        return sum(result.hold_released for result in self.results)


def settled_driver(**overrides) -> Driver:
    driver = Driver(SweepRecognizer(**overrides))
    driver.run(12)  # mão parada por 0,4 s: rastreamento estabilizado
    assert driver.recognizer.state == "TRACKING"
    return driver


def test_rightward_sweep_triggers_once_and_holds_while_moving():
    driver = settled_driver()
    driver.run(20, dx=FAST)
    assert driver.triggers == 1
    assert driver.recognizer.state == "HOLDING"
    assert driver.recognizer.holding is True
    assert driver.releases == 0


def test_hand_stopping_releases_exactly_once():
    driver = settled_driver()
    driver.run(10, dx=FAST)
    assert driver.recognizer.holding
    driver.run(15)  # a mão para
    assert driver.releases == 1
    assert driver.recognizer.state == "COOLDOWN"
    assert driver.recognizer.holding is False


def test_leftward_sweep_does_not_trigger():
    driver = settled_driver()
    driver.run(20, dx=-FAST)
    assert driver.triggers == 0


def test_slow_drift_does_not_trigger():
    driver = settled_driver()
    driver.run(60, dx=SLOW_DRIFT)
    assert driver.triggers == 0


def test_vertical_motion_does_not_trigger():
    driver = settled_driver()
    driver.run(20, dy=FAST)
    assert driver.triggers == 0


def test_diagonal_motion_without_horizontal_dominance_does_not_trigger():
    driver = settled_driver()
    driver.run(20, dx=FAST, dy=FAST)
    assert driver.triggers == 0


def test_closed_hand_sweep_does_not_trigger():
    driver = settled_driver()
    driver.run(20, dx=FAST, closed=True)
    assert driver.triggers == 0


def test_hand_entering_already_moving_does_not_trigger_before_tracking_settles():
    driver = Driver(SweepRecognizer(min_tracking_seconds=0.3))
    driver.run(8, dx=FAST)  # 0,27 s desde que a mão apareceu
    assert driver.triggers == 0


def test_direction_is_relative_to_the_user_when_image_is_not_mirrored():
    unmirrored = settled_driver(mirrored_input=False)
    unmirrored.run(20, dx=FAST)  # para a direita da imagem = esquerda do usuário
    assert unmirrored.triggers == 0

    unmirrored = settled_driver(mirrored_input=False)
    unmirrored.run(20, dx=-FAST)
    assert unmirrored.triggers == 1


def test_left_direction_option():
    driver = settled_driver(direction="left")
    driver.run(20, dx=-FAST)
    assert driver.triggers == 1


def test_brief_noise_does_not_release_hold():
    driver = settled_driver()
    driver.run(10, dx=FAST)
    assert driver.recognizer.holding
    driver.step(dx=FAST, closed=True)  # um quadro ruim
    driver.run(4, dx=FAST)
    assert driver.releases == 0
    assert driver.recognizer.state == "HOLDING"


def test_closing_the_hand_releases_even_if_still_moving():
    driver = settled_driver()
    driver.run(10, dx=FAST)
    driver.run(10, dx=FAST, closed=True)
    assert driver.releases == 1


def test_leftward_return_stroke_releases_and_does_not_retrigger():
    driver = settled_driver()
    driver.run(10, dx=FAST)
    driver.run(15, dx=-FAST)  # volta a mão para a esquerda
    assert driver.releases == 1
    assert driver.triggers == 1


def test_hand_lost_releases_after_grace_period():
    driver = settled_driver(hold_lost_grace_seconds=0.1)
    driver.run(10, dx=FAST)
    assert driver.recognizer.holding
    within_grace = driver.lose(0.05)
    assert within_grace.state == "HOLDING"
    assert within_grace.hold_released is False
    released = driver.lose(0.1)
    assert released.hold_released is True
    assert released.state == "HAND_LOST"


def test_hand_lost_without_hold_does_not_report_release():
    driver = settled_driver()
    lost = driver.lose(0.5)
    assert lost.state == "HAND_LOST"
    assert lost.hold_released is False


def test_max_hold_releases_even_while_still_moving_and_blocks_retrigger():
    driver = settled_driver(max_hold_seconds=0.4)
    driver.run(30, dx=FAST)  # varrida contínua por 1 s
    assert driver.triggers == 1
    assert driver.releases == 1
    assert driver.recognizer.state == "COOLDOWN"  # só rearma quando a mão parar


def test_rearm_needs_cooldown_and_stopped_hand():
    driver = settled_driver(cooldown_seconds=0.5)
    driver.run(10, dx=FAST)
    driver.run(15)  # para e solta
    assert driver.releases == 1
    driver.run(5, dx=FAST)  # varrida durante o cooldown
    assert driver.triggers == 1
    driver.run(30)  # mão parada: cooldown termina e rearma
    assert driver.recognizer.state == "TRACKING"
    driver.run(20, dx=FAST)
    assert driver.triggers == 2


def test_invalid_configuration_is_rejected():
    with pytest.raises(ValueError):
        SweepRecognizer(start_speed=2.0, stop_speed=3.0)
    with pytest.raises(ValueError):
        SweepRecognizer(direction="up")
