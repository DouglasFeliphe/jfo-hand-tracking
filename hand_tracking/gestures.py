from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import time
from typing import Any


@dataclass
class GestureResult:
    state: str
    open_palm: bool
    triggered: bool
    scale_ratio: float
    z_delta: float
    finger_angles: dict[str, float]
    message: str
    hold_released: bool = False  # True uma única vez: o "segurar" terminou (soltar a tecla)


def _xy(landmarks: Any, index: int) -> tuple[float, float]:
    point = landmarks.landmark[index]
    return float(point.x), float(point.y)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _angle(a: tuple[float, float], vertex: tuple[float, float], c: tuple[float, float]) -> float:
    """Return the angle ABC in degrees, with 180 degrees meaning straight."""
    bax = a[0] - vertex[0]
    bay = a[1] - vertex[1]
    bcx = c[0] - vertex[0]
    bcy = c[1] - vertex[1]
    denominator = math.hypot(bax, bay) * math.hypot(bcx, bcy)
    if denominator < 1e-8:
        return 0.0
    cosine = (bax * bcx + bay * bcy) / denominator
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


class GestureRecognizer:
    """Deterministic right-hand open-palm + forward-thrust recognizer.

    MediaPipe's normalized z is used as supporting evidence; apparent palm
    growth is the primary depth cue because monocular z can be noisy.

    After the thrust (`triggered=True`, press the key) the recognizer enters
    HOLDING while the palm stays open and extended. When the pose ends
    (palm closes, hand retracts or is lost) it reports `hold_released=True`
    exactly once (release the key). With `hold_enabled=False` the release is
    reported on the very next frame, which makes the gesture a plain tap.
    """

    MESSAGES = {
        "IDLE": "SHOW RIGHT HAND",
        "TRACKING": "OPEN RIGHT PALM",
        "ARMED": "ARMED - PUSH FORWARD",
        "GESTURE_DETECTED": "FORCE PUSH DETECTED",
        "HOLDING": "HOLDING - CLOSE HAND OR PULL BACK TO RELEASE",
        "COOLDOWN": "RELEASE HAND TO REARM",
        "HAND_LOST": "SHOW RIGHT HAND",
    }

    FINGER_JOINTS = {
        "index": (5, 6, 8),
        "middle": (9, 10, 12),
        "ring": (13, 14, 16),
        "pinky": (17, 18, 20),
    }

    def __init__(
        self,
        open_palm_angle: float = 150.0,
        thumb_spread_ratio: float = 0.42,
        arm_stability_seconds: float = 0.35,
        scale_trigger_ratio: float = 1.15,
        scale_strong_ratio: float = 1.25,
        z_trigger_delta: float = 0.006,
        cooldown_seconds: float = 0.80,
        smoothing_samples: int = 5,
        hold_enabled: bool = True,
        hold_release_ratio: float = 1.04,
        hold_release_seconds: float = 0.15,
        hold_lost_grace_seconds: float = 0.15,
        pinch_exclusion_ratio: float = 0.40,
    ) -> None:
        self.open_palm_angle = open_palm_angle
        self.thumb_spread_ratio = thumb_spread_ratio
        self.arm_stability_seconds = arm_stability_seconds
        self.scale_trigger_ratio = scale_trigger_ratio
        self.scale_strong_ratio = scale_strong_ratio
        self.z_trigger_delta = z_trigger_delta
        self.cooldown_seconds = cooldown_seconds
        self.hold_enabled = hold_enabled
        self.hold_release_ratio = hold_release_ratio
        self.hold_release_seconds = hold_release_seconds
        self.hold_lost_grace_seconds = hold_lost_grace_seconds
        # Polegar a menos que isso (em larguras de palma) da ponta do indicador = pinça,
        # nunca palma aberta. Mantém o empurrão e a lentidão (pinça) mutuamente exclusivos.
        self.pinch_exclusion_ratio = pinch_exclusion_ratio
        self._scale_history: deque[float] = deque(maxlen=max(1, smoothing_samples))
        self._z_history: deque[float] = deque(maxlen=max(1, smoothing_samples))
        self.reset()

    def reset(self) -> None:
        self.state = "IDLE"
        self._open_since: float | None = None
        self._baseline_scale: float | None = None
        self._baseline_z: float | None = None
        self._trigger_time: float | None = None
        self._closed_since: float | None = None
        self._below_since: float | None = None
        self._lost_since: float | None = None
        self._scale_history.clear()
        self._z_history.clear()

    @property
    def holding(self) -> bool:
        """True while the key should be pressed (from the thrust until hold_released)."""
        return self.state in ("GESTURE_DETECTED", "HOLDING")

    def _measure(self, landmarks: Any) -> tuple[bool, dict[str, float], float, float]:
        angles: dict[str, float] = {}
        extended = 0
        for name, (mcp, pip, tip) in self.FINGER_JOINTS.items():
            value = _angle(_xy(landmarks, mcp), _xy(landmarks, pip), _xy(landmarks, tip))
            angles[name] = value
            if value >= self.open_palm_angle:
                extended += 1

        palm_width = _distance(_xy(landmarks, 5), _xy(landmarks, 17))
        thumb_spread = _distance(_xy(landmarks, 4), _xy(landmarks, 5))
        thumb_ratio = thumb_spread / max(palm_width, 1e-6)
        thumb_index_ratio = _distance(_xy(landmarks, 4), _xy(landmarks, 8)) / max(palm_width, 1e-6)
        open_palm = (
            extended == 4
            and thumb_ratio >= self.thumb_spread_ratio
            and thumb_index_ratio > self.pinch_exclusion_ratio
        )

        # Palm scale is less sensitive to finger articulation than the full bbox.
        wrist = _xy(landmarks, 0)
        middle_mcp = _xy(landmarks, 9)
        palm_length = _distance(wrist, middle_mcp)
        scale = (palm_length + palm_width) / 2.0

        z_values = [float(landmarks.landmark[i].z) for i in (0, 5, 9, 17)]
        mean_z = sum(z_values) / len(z_values)
        return open_palm, angles, scale, mean_z

    @staticmethod
    def _median(values: deque[float]) -> float:
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    def update(self, detection: Any | None, now: float | None = None) -> GestureResult:
        now = time.perf_counter() if now is None else now
        if detection is None:
            if self.holding and self.hold_lost_grace_seconds > 0:
                # Tolera perdas curtas de rastreamento sem soltar a tecla.
                if self._lost_since is None:
                    self._lost_since = now
                if now - self._lost_since < self.hold_lost_grace_seconds:
                    return GestureResult(self.state, False, False, 1.0, 0.0, {}, self.MESSAGES[self.state])
            was_holding = self.holding
            self.state = "HAND_LOST"
            self._open_since = None
            self._baseline_scale = None
            self._baseline_z = None
            self._trigger_time = None
            self._closed_since = None
            self._below_since = None
            self._lost_since = None
            self._scale_history.clear()
            self._z_history.clear()
            return GestureResult(self.state, False, False, 1.0, 0.0, {}, "SHOW RIGHT HAND",
                                 hold_released=was_holding)

        self._lost_since = None
        open_palm, angles, raw_scale, raw_z = self._measure(detection.landmarks)
        self._scale_history.append(raw_scale)
        self._z_history.append(raw_z)
        scale = self._median(self._scale_history)
        z_value = self._median(self._z_history)
        scale_ratio = scale / self._baseline_scale if self._baseline_scale else 1.0
        z_delta = z_value - self._baseline_z if self._baseline_z is not None else 0.0
        triggered = False
        hold_released = False

        if self.state in ("IDLE", "HAND_LOST"):
            self.state = "TRACKING"

        if self.state == "TRACKING":
            if open_palm:
                if self._open_since is None:
                    self._open_since = now
                if now - self._open_since >= self.arm_stability_seconds:
                    self.state = "ARMED"
                    self._baseline_scale = scale
                    self._baseline_z = z_value
                    scale_ratio = 1.0
                    z_delta = 0.0
            else:
                self._open_since = None

        elif self.state == "ARMED":
            if not open_palm:
                # Losing the preparation pose cancels the pending gesture.
                self.state = "TRACKING"
                self._open_since = None
                self._baseline_scale = None
                self._baseline_z = None
                scale_ratio = 1.0
                z_delta = 0.0
            else:
                scale_ratio = scale / max(self._baseline_scale or scale, 1e-6)
                z_delta = z_value - (self._baseline_z if self._baseline_z is not None else z_value)
                depth_supported = z_delta <= -self.z_trigger_delta
                if scale_ratio >= self.scale_trigger_ratio and (depth_supported or scale_ratio >= self.scale_strong_ratio):
                    self.state = "GESTURE_DETECTED"
                    self._trigger_time = now
                    triggered = True

        elif self.state == "GESTURE_DETECTED":
            if self.hold_enabled:
                self.state = "HOLDING"
                self._below_since = None
            else:
                self.state = "COOLDOWN"
                hold_released = True

        elif self.state == "HOLDING":
            scale_ratio = scale / max(self._baseline_scale or scale, 1e-6)
            z_delta = z_value - (self._baseline_z if self._baseline_z is not None else z_value)
            pose_ended = (not open_palm) or scale_ratio < self.hold_release_ratio
            if pose_ended:
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
            if elapsed >= self.cooldown_seconds:
                if not open_palm:
                    if self._closed_since is None:
                        self._closed_since = now
                    elif now - self._closed_since >= 0.20:
                        self.state = "TRACKING"
                        self._open_since = None
                        self._baseline_scale = None
                        self._baseline_z = None
                        self._closed_since = None
                else:
                    self._closed_since = None

        return GestureResult(self.state, open_palm, triggered, scale_ratio, z_delta, angles,
                             self.MESSAGES.get(self.state, self.state), hold_released=hold_released)
