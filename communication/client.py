from __future__ import annotations

import json
import socket
import uuid
from dataclasses import dataclass
from typing import Any

# Status em que o adaptador processou o comando com sucesso.
# "not_active" fica de fora de propósito: indica que a tecla já tinha sido solta
# (ex.: soltura automática) e aparece como aviso no painel.
SUCCESS_STATUSES = {"injected", "dry_run", "released", "held", "duplicate", "already_active"}


@dataclass
class SendResult:
    ok: bool          # o adaptador processou o comando com sucesso
    status: str
    message: str
    sequence: int
    delivered: bool = True  # um ACK válido foi recebido (False = falha de comunicação)
    kind: str = ""          # START, STOP ou HEARTBEAT


class GameAdapterClient:
    """Sends one newline-delimited JSON message per TCP connection.

    Messages: ABILITY_START (press), ABILITY_STOP (release) and
    ABILITY_HEARTBEAT (keeps a held key alive). Statuses such as
    `blocked_not_focused` or `rate_limited` are valid ACKs (delivered=True)
    with ok=False: the adapter answered, but the key was not pressed.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, timeout: float = 0.75,
                 auth_token: str | None = None) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.auth_token = auth_token or None
        self.session_id = str(uuid.uuid4())
        self.sequence = 0

    def send_start(self, ability: str = "FORCE_PUSH", hand: str = "RIGHT") -> SendResult:
        return self._send("ABILITY_START", ability, hand)

    def send_stop(self, ability: str = "FORCE_PUSH", hand: str = "RIGHT") -> SendResult:
        return self._send("ABILITY_STOP", ability, hand)

    def send_heartbeat(self, ability: str = "FORCE_PUSH", hand: str = "RIGHT") -> SendResult:
        return self._send("ABILITY_HEARTBEAT", ability, hand)

    def _send(self, message_type: str, ability: str, hand: str) -> SendResult:
        self.sequence += 1
        sequence = self.sequence
        kind = message_type.removeprefix("ABILITY_")
        payload: dict[str, Any] = {
            "type": message_type,
            "ability": ability,
            "hand": hand,
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
                return SendResult(False, "invalid_ack", "Resposta do adaptador não é um ACK.", sequence, False, kind)
            status = str(ack.get("status", "unknown"))
            message = str(ack.get("message", ""))
            if status == "rejected" and ack.get("session_id") is None:
                # Rejeição genérica (ex.: mensagem malformada) não ecoa session_id.
                return SendResult(False, status, message, sequence, True, kind)
            if ack.get("session_id") != self.session_id or ack.get("sequence") != sequence:
                return SendResult(False, "invalid_ack", "Resposta do adaptador não corresponde ao comando.",
                                  sequence, False, kind)
            return SendResult(status in SUCCESS_STATUSES, status, message, sequence, True, kind)
        except (OSError, TimeoutError, json.JSONDecodeError, ValueError) as error:
            return SendResult(False, "unavailable", str(error), sequence, False, kind)

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
