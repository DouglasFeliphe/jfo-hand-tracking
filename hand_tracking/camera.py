from __future__ import annotations

import cv2


class Camera:
    """Small OpenCV webcam wrapper with optional mirrored preview/input."""

    def __init__(self, index: int = 0, width: int = 1280, height: int = 720,
                 fps: int = 30, mirror: bool = True, fourcc: str | None = None,
                 buffer_size: int = 1) -> None:
        self.fourcc = fourcc
        self.buffer_size = buffer_size
        self.index = index
        self.width = width
        self.height = height
        self.fps = fps
        self.mirror = mirror
        self._capture: cv2.VideoCapture | None = None

    def open(self) -> None:
        # CAP_DSHOW generally avoids slow camera initialization on Windows.
        capture = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(self.index)

        if not capture.isOpened():
            raise RuntimeError(
                f"Não foi possível abrir a webcam de índice {self.index}. "
                "Verifique se ela está conectada e se outro programa não está usando-a."
            )

        # Formato de captura (ex.: "MJPG"): muitas webcams USB só chegam a 30 FPS em 720p assim.
        # Precisa ser definido antes da resolução para ter efeito em vários drivers.
        if self.fourcc:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        # Fila de quadros mínima: evita processar imagens atrasadas (ignorado por alguns drivers).
        capture.set(cv2.CAP_PROP_BUFFERSIZE, self.buffer_size)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, self.fps)
        self._capture = capture

    def read(self):
        if self._capture is None:
            raise RuntimeError("A webcam ainda não foi aberta.")

        success, frame = self._capture.read()
        if not success or frame is None:
            return False, None

        # MediaPipe Hands assumes mirrored selfie input for handedness labels.
        # Mirroring before inference makes its Right/Left labels intuitive.
        if self.mirror:
            frame = cv2.flip(frame, 1)

        return True, frame

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
