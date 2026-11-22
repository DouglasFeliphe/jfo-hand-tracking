from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("mediapipe")
pytest.importorskip("cv2")

from hand_tracking.detector import HandDetector  # noqa: E402


def make_detector(results, target="Right", also=(), mirrored=True) -> HandDetector:
    """HandDetector sem criar o modelo do MediaPipe: só a lógica de seleção de mãos."""
    detector = object.__new__(HandDetector)
    detector.target_hand = target
    detector.wanted_hands = {target, *also}
    detector.mirrored_input = mirrored
    detector._hands = SimpleNamespace(process=lambda rgb: results)
    return detector


def fake_results(*hands):
    """hands: (rótulo, confiança, id)"""
    return SimpleNamespace(
        multi_hand_landmarks=[f"lm-{ident}" for _, _, ident in hands],
        multi_handedness=[
            SimpleNamespace(classification=[SimpleNamespace(label=label, score=score)])
            for label, score, _ in hands
        ],
    )


FRAME = np.zeros((4, 4, 3), dtype=np.uint8)


def test_returns_only_target_hand_by_default():
    detector = make_detector(fake_results(("Right", 0.9, 1), ("Left", 0.9, 2)))
    detections, _ = detector.process(FRAME)
    assert [d.handedness for d in detections] == ["Right"]


def test_returns_both_hands_with_target_first():
    detector = make_detector(fake_results(("Left", 0.8, 1), ("Right", 0.9, 2)), also=("Left",))
    detections, _ = detector.process(FRAME)
    assert [d.handedness for d in detections] == ["Right", "Left"]


def test_duplicate_label_keeps_most_confident_detection():
    detector = make_detector(fake_results(("Left", 0.6, 1), ("Left", 0.9, 2)), target="Left")
    detections, _ = detector.process(FRAME)
    assert len(detections) == 1
    assert detections[0].landmarks == "lm-2"


def test_labels_are_swapped_for_unmirrored_input():
    detector = make_detector(fake_results(("Right", 0.9, 1)), target="Left", mirrored=False)
    detections, _ = detector.process(FRAME)
    assert [d.handedness for d in detections] == ["Left"]


def test_no_hands_returns_empty_list():
    detector = make_detector(SimpleNamespace(multi_hand_landmarks=None, multi_handedness=None))
    assert detector.process(FRAME)[0] == []
