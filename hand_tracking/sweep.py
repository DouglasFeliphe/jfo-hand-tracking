from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from hand_tracking.gestures import _angle, _distance, _xy


@dataclass
class SweepResult:
    state: str
    open_palm: bool
    triggered: bool
    speed: float | None  # velocidade na direção configurada, em larguras de palma por segundo
    travel: float        # deslocamento do candidato a varrida, em larguras de palma
    message: str
    hold_released: bool = False  # True uma única vez: a varrida terminou (soltar a tecla)


class SweepRecognizer:
    """Varrida horizontal da mão com a palma aberta ("abrir uma cortina").

    Segue o mesmo contrato do `GestureRecognizer`: `triggered=True` quando a varrida
    é confirmada (pressionar a tecla) e `hold_released=True`, uma única vez, quando a
    mão para ou muda de pose (soltar a tecla). A tecla fica pressionada só durante
    o movimento.

    A velocidade é medida em larguras de palma por segundo (independe da distância
    da mão à câmera) sobre o centro da palma, em uma janela curta. A direção é
    relativa ao usuário: com a imagem espelhada, "right" é o sentido de x crescente.
    """

    FINGER_JOINTS = {
        "index": (5, 6, 8),
        "middle": (9, 10, 12),
        "ring": (13, 14, 16),
        "pinky": (17, 18, 20),
    }
    PALM_POINTS = (0, 5, 9, 13, 17)

    MESSAGES = {
        "IDLE": "SHOW LEFT HAND",
        "TRACKING": "OPEN PALM AND SWEEP RIGHT FOR SLOW",
        "GESTURE_DETECTED": "FORCE SLOW DETECTED",
        "HOLDING": "SLOW - STOP MOVING TO RELEASE",
        "COOLDOWN": "STOP HAND TO REARM",
        "HAND_LOST": "SHOW LEFT HAND",
    }

    def __init__(
        self,
        direction: str = "right",
        mirrored_input: bool = True,
        finger_extended_angle: float = 150.0,
        start_speed: float = 3.0,
        min_travel: float = 0.6,
        stop_speed: float = 1.2,
        stop_seconds: float = 0.12,
        horizontal_dominance: float = 1.5,
        velocity_window_seconds: float = 0.12,
        candidate_timeout_seconds: float = 0.5,
        min_tracking_seconds: float = 0.3,
        max_hold_seconds: float = 2.0,
        cooldown_seconds: float = 0.5,
        hold_lost_grace_seconds: float = 0.1,
    ) -> None:
        if direction not in ("right", "left"):
            raise ValueError("direction deve ser 'right' ou 'left'.")
        if stop_speed >= start_speed:
            raise ValueError("stop_speed deve ser menor que start_speed (histerese).")
        # Espelhada: a direita do usuário é x crescente. Sem espelhar, é x decrescente.
        self._sign = 1.0 if (direction == "right") == mirrored_input else -1.0
        self.direction = direction
        self.finger_extended_angle = finger_extended_angle
        self.start_speed = start_speed
        self.min_travel = min_travel
        self.stop_speed = stop_speed
        self.stop_seconds = stop_seconds
        self.horizontal_dominance = horizontal_dominance
        self.velocity_window_seconds = velocity_window_seconds
        self.candidate_timeout_seconds = candidate_timeout_seconds
        self.min_tracking_seconds = min_tracking_seconds
        self.max_hold_seconds = max_hold_seconds
        self.cooldown_seconds = cooldown_seconds
        self.hold_lost_grace_seconds = hold_lost_grace_seconds
        self._samples: deque[tuple[float, float, float]] = deque()
        self.reset()

    def reset(self) -> None:
        self.state = "IDLE"
        self._tracking_since: float | None = None
        self._candidate: tuple[float, float] | None = None
        self._hold_since: float | None = None
        self._release_time: float | None = None
        self._below_since: float | None = None
        self._lost_since: float | None = None
        self._samples.clear()

    @property
    def holding(self) -> bool:
        """True while the key should be pressed (from the trigger until hold_released)."""
        return self.state in ("GESTURE_DETECTED", "HOLDING")

    def _measure(self, landmarks: Any) -> tuple[bool, float, float, float]:
        extended = all(
            _angle(_xy(landmarks, mcp), _xy(landmarks, pip), _xy(landmarks, tip)) >= self.finger_extended_angle
            for mcp, pip, tip in self.FINGER_JOINTS.values()
        )
        points = [_xy(landmarks, index) for index in self.PALM_POINTS]
        x = sum(point[0] for point in points) / len(points)
        y = sum(point[1] for point in points) / len(points)
        palm_width = _distance(_xy(landmarks, 5), _xy(landmarks, 17))
        palm_length = _distance(_xy(landmarks, 0), _xy(landmarks, 9))
        palm_size = max((palm_width + palm_length) / 2.0, 1e-3)
        return extended, x, y, palm_size

    def _velocity(self, now: float, x: float, y: float, palm_size: float) -> tuple[float, bool]:
        """Velocidade na direção configurada (palmas/s) e se o movimento é predominantemente horizontal."""
        self._samples.append((now, x, y))
        while self._samples and now - self._samples[0][0] > self.velocity_window_seconds:
            self._samples.popleft()
        if len(self._samples) < 2:
            return 0.0, False
        t0, x0, y0 = self._samples[0]
        span = now - t0
        if span < 0.04:
            return 0.0, False
        dx = x - x0
        dy = y - y0
        speed = self._sign * dx / span / palm_size
        horizontal = abs(dx) >= abs(dy) * self.horizontal_dominance
        return speed, horizontal

    def update(self, detection: Any | None, now: float | None = None) -> SweepResult:
        now = time.perf_counter() if now is None else now

        if detection is None:
            if self.holding and self.hold_lost_grace_seconds > 0:
                # Tolera perdas curtas de rastreamento sem soltar a tecla.
                if self._lost_since is None:
                    self._lost_since = now
                if now - self._lost_since < self.hold_lost_grace_seconds:
                    return SweepResult(self.state, False, False, None, 0.0, self.MESSAGES[self.state])
            was_holding = self.holding
            self.reset()
            self.state = "HAND_LOST"
            return SweepResult(self.state, False, False, None, 0.0, self.MESSAGES["HAND_LOST"],
                               hold_released=was_holding)

        self._lost_since = None
        open_palm, x, y, palm_size = self._measure(detection.landmarks)
        speed, horizontal = self._velocity(now, x, y, palm_size)
        triggered = False
        hold_released = False
        travel = 0.0

        if self.state in ("IDLE", "HAND_LOST"):
            self.state = "TRACKING"
            self._tracking_since = now

        if self.state == "TRACKING":
            settled = now - (self._tracking_since if self._tracking_since is not None else now) >= self.min_tracking_seconds
            if not open_palm or not horizontal or speed < self.start_speed * 0.5:
                self._candidate = None
            elif settled:
                if self._candidate is None and speed >= self.start_speed:
                    self._candidate = (now, x)
                if self._candidate is not None:
                    start_time, start_x = self._candidate
                    if now - start_time > self.candidate_timeout_seconds:
                        self._candidate = None
                    else:
                        travel = self._sign * (x - start_x) / palm_size
                        if travel >= self.min_travel:
                            self.state = "GESTURE_DETECTED"
                            self._hold_since = now
                            self._below_since = None
                            self._candidate = None
                            triggered = True

        elif self.state == "GESTURE_DETECTED":
            self.state = "HOLDING"

        elif self.state == "HOLDING":
            moving = open_palm and speed >= self.stop_speed
            if moving:
                self._below_since = None
            else:
                if self._below_since is None:
                    self._below_since = now
            stopped = self._below_since is not None and now - self._below_since >= self.stop_seconds
            too_long = self._hold_since is not None and now - self._hold_since >= self.max_hold_seconds
            if stopped or too_long:
                self.state = "COOLDOWN"
                self._release_time = now
                self._below_since = None
                hold_released = True

        elif self.state == "COOLDOWN":
            elapsed = now - (self._release_time if self._release_time is not None else now)
            # Só rearma depois do tempo de espera e com a mão praticamente parada.
            if elapsed >= self.cooldown_seconds and speed < self.start_speed * 0.5:
                self.state = "TRACKING"
                self._candidate = None

        return SweepResult(self.state, open_palm, triggered, speed, travel,
                           self.MESSAGES.get(self.state, self.state), hold_released=hold_released)
