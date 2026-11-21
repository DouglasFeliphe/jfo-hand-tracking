from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from hand_tracking.gestures import _angle, _distance, _xy


@dataclass
class PinchResult:
    state: str
    pinching: bool
    triggered: bool
    pinch_ratio: float | None  # distância polegar-indicador / largura da palma (None sem mão)
    message: str
    hold_released: bool = False  # True uma única vez: o "segurar" terminou (soltar a tecla)


class PinchRecognizer:
    """Pinça (sinal de "OK"): polegar tocando o indicador, com médio, anelar e mínimo estendidos.

    Segue o mesmo contrato do `GestureRecognizer`: `triggered=True` quando a pinça
    fica estável (pressionar a tecla) e `hold_released=True`, uma única vez, quando
    ela termina (soltar a tecla). Usa apenas distâncias e ângulos no plano da imagem,
    sem escala nem profundidade (z), que são mais ruidosos.

    A pinça nunca coincide com a palma aberta do empurrão (polegar afastado, quatro
    dedos estendidos), então os dois reconhecedores não se confundem.
    """

    FINGER_JOINTS = {
        "middle": (9, 10, 12),
        "ring": (13, 14, 16),
        "pinky": (17, 18, 20),
    }

    MESSAGES = {
        "IDLE": "SHOW RIGHT HAND",
        "TRACKING": "PINCH THUMB + INDEX FOR SLOW",
        "GESTURE_DETECTED": "FORCE SLOW DETECTED",
        "HOLDING": "SLOW - OPEN PINCH TO RELEASE",
        "COOLDOWN": "OPEN PINCH TO REARM",
        "HAND_LOST": "SHOW RIGHT HAND",
    }

    def __init__(
        self,
        pinch_close_ratio: float = 0.28,
        pinch_open_ratio: float = 0.40,
        finger_extended_angle: float = 150.0,
        stability_seconds: float = 0.20,
        cooldown_seconds: float = 0.40,
        hold_enabled: bool = True,
        hold_release_seconds: float = 0.15,
        hold_lost_grace_seconds: float = 0.15,
    ) -> None:
        if pinch_close_ratio >= pinch_open_ratio:
            raise ValueError("pinch_close_ratio deve ser menor que pinch_open_ratio (histerese).")
        self.pinch_close_ratio = pinch_close_ratio
        self.pinch_open_ratio = pinch_open_ratio
        self.finger_extended_angle = finger_extended_angle
        self.stability_seconds = stability_seconds
        self.cooldown_seconds = cooldown_seconds
        self.hold_enabled = hold_enabled
        self.hold_release_seconds = hold_release_seconds
        self.hold_lost_grace_seconds = hold_lost_grace_seconds
        self.reset()

    def reset(self) -> None:
        self.state = "IDLE"
        self._pinch_since: float | None = None
        self._below_since: float | None = None
        self._lost_since: float | None = None
        self._trigger_time: float | None = None

    @property
    def holding(self) -> bool:
        """True while the key should be pressed (from the trigger until hold_released)."""
        return self.state in ("GESTURE_DETECTED", "HOLDING")

    def _measure(self, landmarks: Any) -> tuple[float, dict[str, float]]:
        palm_width = max(_distance(_xy(landmarks, 5), _xy(landmarks, 17)), 1e-6)
        ratio = _distance(_xy(landmarks, 4), _xy(landmarks, 8)) / palm_width
        angles = {
            name: _angle(_xy(landmarks, mcp), _xy(landmarks, pip), _xy(landmarks, tip))
            for name, (mcp, pip, tip) in self.FINGER_JOINTS.items()
        }
        return ratio, angles

    def update(self, detection: Any | None, now: float | None = None,
               suppressed: bool = False) -> PinchResult:
        """`suppressed=True` impede um novo disparo (ex.: outro gesto está segurando)."""
        now = time.perf_counter() if now is None else now

        if detection is None:
            if self.holding and self.hold_lost_grace_seconds > 0:
                # Tolera perdas curtas de rastreamento sem soltar a tecla.
                if self._lost_since is None:
                    self._lost_since = now
                if now - self._lost_since < self.hold_lost_grace_seconds:
                    return PinchResult(self.state, False, False, None, self.MESSAGES[self.state])
            was_holding = self.holding
            self.reset()
            self.state = "HAND_LOST"
            return PinchResult(self.state, False, False, None, self.MESSAGES["HAND_LOST"],
                               hold_released=was_holding)

        self._lost_since = None
        ratio, angles = self._measure(detection.landmarks)
        # Histerese: iniciar exige a pinça "fechada"; mantê-la tolera um pouco mais.
        others_to_start = all(angle >= self.finger_extended_angle for angle in angles.values())
        others_to_keep = all(angle >= self.finger_extended_angle - 10.0 for angle in angles.values())
        engaged = ratio <= self.pinch_close_ratio and others_to_start
        kept = ratio <= self.pinch_open_ratio and others_to_keep
        triggered = False
        hold_released = False

        if self.state in ("IDLE", "HAND_LOST"):
            self.state = "TRACKING"

        if self.state == "TRACKING":
            if engaged and not suppressed:
                if self._pinch_since is None:
                    self._pinch_since = now
                if now - self._pinch_since >= self.stability_seconds:
                    self.state = "GESTURE_DETECTED"
                    self._trigger_time = now
                    self._pinch_since = None
                    triggered = True
            else:
                self._pinch_since = None

        elif self.state == "GESTURE_DETECTED":
            if self.hold_enabled:
                self.state = "HOLDING"
                self._below_since = None
            else:
                self.state = "COOLDOWN"
                hold_released = True

        elif self.state == "HOLDING":
            if not kept:
                if self._below_since is None:
                    self._below_since = now
                if now - self._below_since >= self.hold_release_seconds:
                    self.state = "COOLDOWN"
                    self._below_since = None
                    hold_released = True
            else:
                self._below_since = None

        elif self.state == "COOLDOWN":
            elapsed = now - (self._trigger_time if self._trigger_time is not None else now)
            # Só rearma depois do tempo de espera e com a pinça desfeita.
            if elapsed >= self.cooldown_seconds and not engaged:
                self.state = "TRACKING"
                self._pinch_since = None

        return PinchResult(self.state, engaged or kept and self.holding, triggered, ratio,
                           self.MESSAGES.get(self.state, self.state), hold_released=hold_released)
