from __future__ import annotations

import json
import time
from pathlib import Path

import cv2

from hand_tracking.camera import Camera
from hand_tracking.detector import HandDetector
from hand_tracking.landmarks import LandmarkVisualizer


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "settings.json"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def main() -> int:
    config = load_config()
    camera_config = config["camera"]
    tracking_config = config["tracking"]
    display_config = config["display"]

    camera = Camera(**camera_config)
    detector = HandDetector(
        max_hands=tracking_config["max_hands"],
        model_complexity=tracking_config["model_complexity"],
        detection_confidence=tracking_config["detection_confidence"],
        tracking_confidence=tracking_config["tracking_confidence"],
        target_hand=tracking_config["target_hand"],
        mirrored_input=camera_config["mirror"],
    )
    visualizer = LandmarkVisualizer(
        show_indices=tracking_config["show_landmark_indices"]
    )

    window_title = display_config["window_title"]
    exit_key = display_config["exit_key"].lower()
    previous_time = time.perf_counter()
    fps = 0.0

    try:
        camera.open()
        print("[JFO Hand Tracking] Webcam iniciada.")
        print(f"[JFO Hand Tracking] Mão configurada: {tracking_config['target_hand']}.")
        print(f"[JFO Hand Tracking] Pressione '{exit_key}' para sair.")

        while True:
            success, frame = camera.read()
            if not success:
                print("[AVISO] Não foi possível ler um frame da webcam.")
                break

            detections, _ = detector.process(frame)
            visualizer.draw(frame, detections)

            now = time.perf_counter()
            delta = now - previous_time
            previous_time = now
            if delta > 0:
                instantaneous_fps = 1.0 / delta
                fps = instantaneous_fps if fps == 0 else (0.9 * fps + 0.1 * instantaneous_fps)

            if detections:
                status = "RIGHT HAND DETECTED"
                status_color = (70, 220, 100)
            else:
                status = "SHOW YOUR RIGHT HAND"
                status_color = (0, 190, 255)

            cv2.rectangle(frame, (10, 10), (390, 78), (25, 25, 25), -1)
            cv2.putText(frame, status, (22, 38), cv2.FONT_HERSHEY_SIMPLEX,
                        0.65, status_color, 2, cv2.LINE_AA)
            cv2.putText(frame, f"Hands tracked: {len(detections)}", (22, 64),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1,
                        cv2.LINE_AA)

            if tracking_config["show_fps"]:
                cv2.putText(frame, f"FPS: {fps:.1f}", (frame.shape[1] - 125, 32),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255),
                            2, cv2.LINE_AA)

            cv2.imshow(window_title, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord(exit_key):
                break

    except KeyboardInterrupt:
        print("\n[JFO Hand Tracking] Encerrado pelo usuário.")
    except Exception as error:
        print(f"[ERRO] {error}")
        return 1
    finally:
        camera.close()
        detector.close()
        cv2.destroyAllWindows()
        print("[JFO Hand Tracking] Recursos liberados.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
