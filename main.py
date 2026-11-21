from __future__ import annotations

import json
import time
from pathlib import Path

import cv2

from hand_tracking.camera import Camera
from hand_tracking.detector import HandDetector
from hand_tracking.gestures import GestureRecognizer
from hand_tracking.landmarks import LandmarkVisualizer
from hand_tracking.pinch import PinchRecognizer
from communication.async_sender import AsyncSender
from communication.client import GameAdapterClient, SendResult

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "settings.json"

PUSH_ABILITY = "FORCE_PUSH"  # empurrão: palma aberta + avanço
SLOW_ABILITY = "FORCE_SLOW"  # lentidão: pinça (polegar + indicador)

GREEN = (70, 230, 100)
ORANGE = (0, 165, 255)
YELLOW = (0, 220, 255)
GRAY = (220, 220, 220)


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


def adapter_line(result: SendResult | None) -> tuple[str, tuple[int, int, int]]:
    """Texto e cor do status do adaptador exibido no painel."""
    if result is None:
        return "ADAPTER: NO COMMAND YET", GRAY
    if not result.delivered:
        return "ADAPTER: UNAVAILABLE", ORANGE
    label = f"ADAPTER: {result.status.upper()}"
    if result.ability:
        label += f" ({result.ability.removeprefix('FORCE_')})"
    if result.ok:
        return label, GREEN
    # ACK válido, mas o jogo não recebeu a tecla (foco, intervalo mínimo, falha...).
    return label, YELLOW


def state_color(state: str) -> tuple[int, int, int]:
    if state in ("GESTURE_DETECTED", "HOLDING"):
        return GREEN
    if state == "ARMED":
        return YELLOW
    if state in ("HAND_LOST", "IDLE"):
        return ORANGE
    return GRAY


def log_result(result: SendResult) -> None:
    print(f"[TCP] {result.kind} {result.ability} seq={result.sequence} "
          f"status={result.status} | {result.message}")


def dispatch(sender: AsyncSender, ability: str, result) -> None:
    """Traduz os eventos de um reconhecedor em START/STOP para o adaptador."""
    if result.triggered and not sender.start_ability(ability):
        print(f"[AVISO] Fila de envio cheia; START de {ability} descartado.")
    if result.hold_released and not sender.stop_ability(ability):
        print(f"[AVISO] Fila de envio cheia; STOP de {ability} não enviado "
              "(o adaptador solta a tecla sozinho).")


def main() -> int:
    config = load_config()
    camera_config = config["camera"]
    tracking_config = config["tracking"]
    gesture_config = config["gestures"]
    display_config = config["display"]
    communication_config = config.get("communication", {})
    game_config = config.get("game", {})
    slow_config = dict(config.get("slow_gesture", {}))

    adapter_client = GameAdapterClient(
        host=communication_config.get("host", "127.0.0.1"),
        port=communication_config.get("port", 8765),
        timeout=communication_config.get("timeout_seconds", 0.75),
        auth_token=game_config.get("auth_token"),
    )
    sender = AsyncSender(
        adapter_client,
        on_result=log_result,
        heartbeat_interval=float(communication_config.get("heartbeat_seconds", 0.15)),
    )

    camera = Camera(**camera_config)
    detector = HandDetector(
        max_hands=tracking_config["max_hands"],
        model_complexity=tracking_config["model_complexity"],
        detection_confidence=tracking_config["detection_confidence"],
        tracking_confidence=tracking_config["tracking_confidence"],
        target_hand=tracking_config["target_hand"],
        mirrored_input=camera_config["mirror"],
    )
    push = GestureRecognizer(**gesture_config)
    slow_enabled = bool(slow_config.pop("enabled", True))
    slow = PinchRecognizer(**slow_config) if slow_enabled else None
    visualizer = LandmarkVisualizer(show_indices=tracking_config["show_landmark_indices"])

    window_title = display_config["window_title"]
    exit_key = display_config["exit_key"].lower()
    processing_width = int(display_config.get("processing_width", 640))
    previous_time = time.perf_counter()
    fps = 0.0

    try:
        camera.open()
        sender.start()
        print("[JFO Hand Tracking] Webcam iniciada.")
        print(f"[JFO Hand Tracking] Mão configurada: {tracking_config['target_hand']}.")
        print("[JFO Hand Tracking] Fase 4: gesto -> TCP (START/STOP/HEARTBEAT) -> adaptador -> jogo.")
        print(f"[JFO Hand Tracking] Empurrão ({PUSH_ABILITY}): palma aberta + avanço.")
        if slow is not None:
            print(f"[JFO Hand Tracking] Lentidão ({SLOW_ABILITY}): pinça com polegar e indicador.")
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
                processing_frame = cv2.resize(frame, (processing_width, processing_height),
                                              interpolation=cv2.INTER_AREA)
            else:
                processing_frame = frame

            detections, _ = detector.process(processing_frame)
            visualizer.draw(frame, detections)
            detection = detections[0] if detections else None

            result = push.update(detection)
            # Uma mão, um gesto por vez: a pinça espera o empurrão terminar.
            slow_result = slow.update(detection, suppressed=push.holding) if slow is not None else None

            now = time.perf_counter()
            delta = now - previous_time
            previous_time = now
            if delta > 0:
                instantaneous_fps = 1.0 / delta
                fps = instantaneous_fps if fps == 0 else (0.9 * fps + 0.1 * instantaneous_fps)

            adapter_text, adapter_color = adapter_line(sender.last_result)
            push_color = state_color(result.state)
            lines = [
                (f"STATE: {result.state}", push_color),
                (f"GESTURE: {result.message}", push_color),
                (f"OPEN PALM: {'YES' if result.open_palm else 'NO'}", GRAY),
                (f"PALM SCALE: {result.scale_ratio:.2f}x  |  Z DELTA: {result.z_delta:+.3f}", GRAY),
            ]
            if slow_result is not None:
                slow_color = state_color(slow_result.state)
                ratio = "--" if slow_result.pinch_ratio is None else f"{slow_result.pinch_ratio:.2f}"
                lines.append((f"SLOW: {slow_result.state}  |  PINCH: {ratio}", slow_color))
                lines.append((f"SLOW: {slow_result.message}", slow_color))
            lines.append((adapter_text, adapter_color))
            if tracking_config["show_fps"]:
                lines.append((f"FPS: {fps:.1f}", (255, 255, 255)))
            draw_panel(frame, lines)

            dispatch(sender, PUSH_ABILITY, result)
            if slow_result is not None:
                dispatch(sender, SLOW_ABILITY, slow_result)

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
        # Nunca sai deixando uma tecla pressionada.
        if push.holding:
            sender.stop_ability(PUSH_ABILITY)
        if slow is not None and slow.holding:
            sender.stop_ability(SLOW_ABILITY)
        sender.close()
        camera.close()
        detector.close()
        cv2.destroyAllWindows()
        print("[JFO Hand Tracking] Recursos liberados.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
