from __future__ import annotations

import json
import socket
import uuid
from dataclasses import dataclass
from typing import Any

# Status em que o comando foi recebido/processado com sucesso pelo adaptador.
SUCCESS_STATUSES = {"received", "duplicate", "injected", "dry_run"}


@dataclass
class SendResult:
    ok: bool          # o adaptador processou o comando com sucesso
    status: str
    message: str
    sequence: int
    delivered: bool = True  # um ACK válido foi recebido (False = falha de comunicação)


class GameAdapterClient:
    """Sends one newline-delimited JSON command per TCP connection.

    The client talks only to localhost. Statuses such as `blocked_not_focused`
    or `rate_limited` are valid ACKs (delivered=True) with ok=False: the
    adapter answered, but the game did not receive the key press.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, timeout: float = 0.75,
                 auth_token: str | None = None) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.auth_token = auth_token or None
        self.session_id = str(uuid.uuid4())
        self.sequence = 0

    def send_force_push(self) -> SendResult:
        self.sequence += 1
        sequence = self.sequence
        payload: dict[str, Any] = {
            "type": "ABILITY_TRIGGER",
            "ability": "FORCE_PUSH",
            "hand": "RIGHT",
            "session_id": self.session_id,
            "sequence": sequence,
        }
        if self.auth_token:
            payload["token"] = self.auth_token
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as connection:
                connection.settimeout(self.timeout)
                connection.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
                response = self._read_line(connection)
            ack: dict[str, Any] = json.loads(response)
            if ack.get("type") != "ACK":
                return SendResult(False, "invalid_ack", "Resposta do adaptador não é um ACK.", sequence, False)
            status = str(ack.get("status", "unknown"))
            message = str(ack.get("message", ""))
            if status == "rejected" and ack.get("session_id") is None:
                # Rejeição genérica (ex.: mensagem malformada) não ecoa session_id.
                return SendResult(False, status, message, sequence, True)
            if ack.get("session_id") != self.session_id or ack.get("sequence") != sequence:
                return SendResult(False, "invalid_ack", "Resposta do adaptador não corresponde ao comando.", sequence, False)
            return SendResult(status in SUCCESS_STATUSES, status, message, sequence, True)
        except (OSError, TimeoutError, json.JSONDecodeError, ValueError) as error:
            return SendResult(False, "unavailable", str(error), sequence, False)

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
