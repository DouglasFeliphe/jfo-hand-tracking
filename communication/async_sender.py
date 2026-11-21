from __future__ import annotations

import queue
import threading
from typing import Callable

from communication.client import GameAdapterClient, SendResult

_STOP = object()


class AsyncSender:
    """Envia comandos FORCE_PUSH em uma thread própria, sem bloquear o loop de vídeo."""

    def __init__(
        self,
        client: GameAdapterClient,
        on_result: Callable[[SendResult], None] | None = None,
        maxsize: int = 4,
    ) -> None:
        self._client = client
        self._on_result = on_result
        self._queue: queue.Queue[object] = queue.Queue(maxsize=maxsize)
        self._thread = threading.Thread(target=self._run, name="adapter-sender", daemon=True)
        self.last_result: SendResult | None = None

    def start(self) -> None:
        self._thread.start()

    def submit_force_push(self) -> bool:
        """Enfileira um envio. Retorna False se a fila estiver cheia (comando descartado)."""
        try:
            self._queue.put_nowait(True)
            return True
        except queue.Full:
            return False

    def close(self, timeout: float = 2.0) -> None:
        try:
            self._queue.put(_STOP, timeout=0.2)
        except queue.Full:
            return  # a thread é daemon e termina com o processo
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                break
            result = self._client.send_force_push()
            self.last_result = result
            if self._on_result is not None:
                self._on_result(result)
