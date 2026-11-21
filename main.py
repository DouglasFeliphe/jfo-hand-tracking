from __future__ import annotations

import json
import time
from pathlib import Path

import cv2

from hand_tracking.camera import Camera
from hand_tracking.detector import HandDetector
from hand_tracking.gestures import GestureRecognizer
from hand_tracking.landmarks import LandmarkVisualizer
from communication.client import GameAdapterClient

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "settings.json"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def draw_panel(frame, lines: list[tuple[str, tuple[int, int, int]]]) -> None:
    panel_width = min(frame.shape[1] - 20, 520)
    panel_height = 18 + 27 * len(lines)
    cv2.rectangle(frame, (10, 10), (10 + panel_width, 10 + panel_height), (25, 25, 25), -1)
    for index, (text, color) in enumerate(lines):
        cv2.putText(frame, text, (22, 36 + index * 27), cv2.FONT_HERSHEY_SIMPLEX,
                    0.58, color, 2, cv2.LINE_AA)


def main() -> int:
    config = load_config()
    camera_config = config["camera"]
    tracking_config = config["tracking"]
    gesture_config = config["gestures"]
    display_config = config["display"]
    communication_config = config.get("communication", {})
    adapter_client = GameAdapterClient(
        host=communication_config.get("host", "127.0.0.1"),
        port=communication_config.get("port", 8765),
        timeout=communication_config.get("timeout_seconds", 0.75),
    )
    last_adapter_status = "NOT CONNECTED"

    camera = Camera(**camera_config)
    detector = HandDetector(
        max_hands=tracking_config["max_hands"],
        model_complexity=tracking_config["model_complexity"],
        detection_confidence=tracking_config["detection_confidence"],
        tracking_confidence=tracking_config["tracking_confidence"],
        target_hand=tracking_config["target_hand"],
        mirrored_input=camera_config["mirror"],
    )
    recognizer = GestureRecognizer(**gesture_config)
    visualizer = LandmarkVisualizer(show_indices=tracking_config["show_landmark_indices"])

    window_title = display_config["window_title"]
    exit_key = display_config["exit_key"].lower()
    processing_width = int(display_config.get("processing_width", 640))
    previous_time = time.perf_counter()
    fps = 0.0
    last_result = None

    try:
        camera.open()
        print("[JFO Hand Tracking] Webcam iniciada.")
        print(f"[JFO Hand Tracking] Mão configurada: {tracking_config['target_hand']}.")
        print("[JFO Hand Tracking] Fase 3: comandos FORCE_PUSH via TCP para o adaptador de teste.")
        print(r"[JFO Hand Tracking] Inicie primeiro: .venv\Scripts\python.exe -m adapter.server")
        print(f"[JFO Hand Tracking] Pressione '{exit_key}' para sair.")

        while True:
            success, frame = camera.read()
            if not success:
                print("[AVISO] Não foi possível ler um frame da webcam.")
                break

            original_height, original_width = frame.shape[:2]
            if processing_width > 0 and original_width > processing_width:
                processing_height = round(original_height * processing_width / original_width)
                processing_frame = cv2.resize(frame, (processing_width, processing_height), interpolation=cv2.INTER_AREA)
            else:
                processing_frame = frame

            detections, _ = detector.process(processing_frame)
            visualizer.draw(frame, detections)
            detection = detections[0] if detections else None
            result = recognizer.update(detection)
            last_result = result

            now = time.perf_counter()
            delta = now - previous_time
            previous_time = now
            if delta > 0:
                instantaneous_fps = 1.0 / delta
                fps = instantaneous_fps if fps == 0 else (0.9 * fps + 0.1 * instantaneous_fps)

            if result.state == "GESTURE_DETECTED":
                state_color = (70, 230, 100)
            elif result.state == "ARMED":
                state_color = (0, 220, 255)
            elif result.state in ("HAND_LOST", "IDLE"):
                state_color = (0, 165, 255)
            else:
                state_color = (220, 220, 220)

            lines = [
                (f"STATE: {result.state}", state_color),
                (f"GESTURE: {result.message}", state_color),
                (f"OPEN PALM: {'YES' if result.open_palm else 'NO'}", (220, 220, 220)),
                (f"PALM SCALE: {result.scale_ratio:.2f}x  |  Z DELTA: {result.z_delta:+.3f}", (220, 220, 220)),
                (f"ADAPTER: {last_adapter_status}", (70, 230, 100) if last_adapter_status == "ACK RECEIVED" else (0, 165, 255)),
            ]
            if tracking_config["show_fps"]:
                lines.append((f"FPS: {fps:.1f}", (255, 255, 255)))
            draw_panel(frame, lines)

            if result.triggered:
                send_result = adapter_client.send_force_push()
                if send_result.ok:
                    last_adapter_status = "ACK RECEIVED"
                    print(f"[TCP] FORCE_PUSH seq={send_result.sequence} confirmado pelo adaptador: {send_result.status}")
                    print(f"[TCP] {send_result.message}")
                else:
                    last_adapter_status = "UNAVAILABLE"
                    print(f"[TCP] Falha ao enviar FORCE_PUSH seq={send_result.sequence}: {send_result.message}")

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
