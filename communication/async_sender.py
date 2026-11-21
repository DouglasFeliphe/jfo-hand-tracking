from __future__ import annotations

import queue
import threading
from typing import Callable

from communication.client import GameAdapterClient, SendResult

_STOP_THREAD = object()
STOP_ATTEMPTS = 3


class AsyncSender:
    """Envia START/STOP/HEARTBEAT em uma thread própria, sem bloquear o loop de vídeo.

    - START e STOP passam por uma fila e nunca são descartados silenciosamente.
    - Enquanto uma habilidade está pressionada, a própria thread envia heartbeats
      (não passam pela fila, então nunca atrasam um STOP).
    - STOP é reenviado se a comunicação falhar; o watchdog do adaptador é a segunda barreira.
    """

    def __init__(
        self,
        client: GameAdapterClient,
        on_result: Callable[[SendResult], None] | None = None,
        heartbeat_interval: float = 0.15,
        maxsize: int = 32,
    ) -> None:
        self._client = client
        self._on_result = on_result
        self._heartbeat_interval = heartbeat_interval
        self._queue: queue.Queue[object] = queue.Queue(maxsize=maxsize)
        self._thread = threading.Thread(target=self._run, name="adapter-sender", daemon=True)
        self._active: set[str] = set()  # acessado apenas pela thread de envio
        self.last_result: SendResult | None = None

    def start(self) -> None:
        self._thread.start()

    def start_ability(self, ability: str) -> bool:
        return self._enqueue(("START", ability), timeout=0.0)

    def stop_ability(self, ability: str) -> bool:
        return self._enqueue(("STOP", ability), timeout=0.2)

    def close(self, timeout: float = 3.0) -> None:
        try:
            self._queue.put(_STOP_THREAD, timeout=0.5)
        except queue.Full:
            return  # a thread é daemon; o watchdog do adaptador solta a tecla
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _enqueue(self, item: tuple[str, str], timeout: float) -> bool:
        try:
            if timeout > 0:
                self._queue.put(item, timeout=timeout)
            else:
                self._queue.put_nowait(item)
            return True
        except queue.Full:
            return False

    def _report(self, result: SendResult) -> None:
        self.last_result = result
        if self._on_result is not None:
            self._on_result(result)

    def _run(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=self._heartbeat_interval)
            except queue.Empty:
                self._send_heartbeats()
                continue
            if item is _STOP_THREAD:
                break
            kind, ability = item  # type: ignore[misc]
            if kind == "START":
                result = self._client.send_start(ability)
                if result.ok:
                    self._active.add(ability)
                self._report(result)
            else:
                self._active.discard(ability)  # antes de enviar: nenhum heartbeat depois do STOP
                result = self._client.send_stop(ability)
                for _ in range(STOP_ATTEMPTS - 1):
                    if result.delivered:
                        break
                    result = self._client.send_stop(ability)
                self._report(result)

    def _send_heartbeats(self) -> None:
        for ability in list(self._active):
            result = self._client.send_heartbeat(ability)
            if result.status == "held":
                continue
            # A tecla foi solta pelo adaptador (ou ele ficou indisponível): para de enviar.
            self._active.discard(ability)
            self._report(result)
