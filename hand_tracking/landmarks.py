from __future__ import annotations

import cv2
import mediapipe as mp


class LandmarkVisualizer:
    def __init__(self, show_indices: bool = False) -> None:
        self.show_indices = show_indices
        self.connections = mp.solutions.hands.HAND_CONNECTIONS
        self.landmark_style = mp.solutions.drawing_styles.get_default_hand_landmarks_style()
        self.connection_style = mp.solutions.drawing_styles.get_default_hand_connections_style()

    def draw(self, frame, detections) -> None:
        height, width = frame.shape[:2]
        for detection in detections:
            mp.solutions.drawing_utils.draw_landmarks(
                frame,
                detection.landmarks,
                self.connections,
                self.landmark_style,
                self.connection_style,
            )

            wrist = detection.landmarks.landmark[0]
            x = max(10, min(width - 220, int(wrist.x * width)))
            y = max(30, min(height - 10, int(wrist.y * height)))
            cv2.putText(
                frame,
                f"{detection.handedness} hand  {detection.confidence:.2f}",
                (x, max(25, y - 18)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (70, 220, 100),
                2,
                cv2.LINE_AA,
            )

            if self.show_indices:
                for index, point in enumerate(detection.landmarks.landmark):
                    px, py = int(point.x * width), int(point.y * height)
                    cv2.putText(
                        frame, str(index), (px + 4, py - 4),
                        cv2.FONT_HERSHEY_PLAIN, 0.8, (255, 220, 60), 1,
                        cv2.LINE_AA,
                    )
