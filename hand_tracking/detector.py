from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import mediapipe as mp


@dataclass
class HandDetection:
    handedness: str
    confidence: float
    landmarks: Any
    world_landmarks: Any | None = None


class HandDetector:
    """MediaPipe Hands detector. Returns only the configured target hand."""

    def __init__(self, max_hands: int = 1, model_complexity: int = 1,
                 detection_confidence: float = 0.7,
                 tracking_confidence: float = 0.65,
                 target_hand: str = "Right",
                 mirrored_input: bool = True) -> None:
        if target_hand not in ("Right", "Left"):
            raise ValueError("target_hand deve ser 'Right' ou 'Left'.")

        self.target_hand = target_hand
        self.mirrored_input = mirrored_input
        self._mp_hands = mp.solutions.hands
        self._mp_drawing = mp.solutions.drawing_utils
        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=max_hands,
            model_complexity=model_complexity,
            min_detection_confidence=detection_confidence,
            min_tracking_confidence=tracking_confidence,
        )

    def process(self, frame_bgr) -> tuple[list[HandDetection], Any]:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self._hands.process(rgb)
        rgb.flags.writeable = True

        detections: list[HandDetection] = []
        if not results.multi_hand_landmarks or not results.multi_handedness:
            return detections, results

        for landmarks, handedness in zip(
            results.multi_hand_landmarks, results.multi_handedness
        ):
            classification = handedness.classification[0]
            label = classification.label
            # MediaPipe Hands assumes mirrored selfie input for handedness.
            # Swap labels when the caller supplies an unmirrored frame.
            if not self.mirrored_input:
                label = "Left" if label == "Right" else "Right"
            confidence = float(classification.score)

            if label == self.target_hand:
                detections.append(
                    HandDetection(
                        handedness=label,
                        confidence=confidence,
                        landmarks=landmarks,
                    )
                )

        return detections, results

    def close(self) -> None:
        self._hands.close()

    def __enter__(self) -> "HandDetector":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
