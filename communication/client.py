from __future__ import annotations

import json
import socket
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class SendResult:
    ok: bool
    status: str
    message: str
    sequence: int


class GameAdapterClient:
    """Sends one newline-delimited JSON command per TCP connection.

    The client talks only to localhost. An ACK confirms receipt by the adapter,
    not execution inside Jedi: Fallen Order.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, timeout: float = 0.75) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.session_id = str(uuid.uuid4())
        self.sequence = 0

    def send_force_push(self) -> SendResult:
        self.sequence += 1
        sequence = self.sequence
        payload = {
            "type": "ABILITY_TRIGGER",
            "ability": "FORCE_PUSH",
            "hand": "RIGHT",
            "session_id": self.session_id,
            "sequence": sequence,
        }
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as connection:
                connection.settimeout(self.timeout)
                connection.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
                response = self._read_line(connection)
            ack: dict[str, Any] = json.loads(response)
            if ack.get("type") != "ACK" or ack.get("session_id") != self.session_id or ack.get("sequence") != sequence:
                return SendResult(False, "invalid_ack", "Resposta do adaptador não corresponde ao comando.", sequence)
            status = str(ack.get("status", "unknown"))
            accepted = status in {"received", "duplicate"}
            return SendResult(accepted, status, str(ack.get("message", "")), sequence)
        except (OSError, TimeoutError, json.JSONDecodeError, ValueError) as error:
            return SendResult(False, "unavailable", str(error), sequence)

    @staticmethod
    def _read_line(connection: socket.socket, max_bytes: int = 8192) -> str:
        data = bytearray()
        while len(data) < max_bytes:
            chunk = connection.recv(1)
            if not chunk:
                break
            if chunk == b"\n":
                return data.decode("utf-8")
            data.extend(chunk)
        if len(data) >= max_bytes:
            raise ValueError("ACK excedeu o tamanho máximo permitido.")
        if not data:
            raise ConnectionError("O adaptador encerrou a conexão sem enviar ACK.")
        return data.decode("utf-8")
