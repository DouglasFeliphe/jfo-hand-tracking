from __future__ import annotations

import json
import socket
import threading
from contextlib import contextmanager

from adapter.server import AdapterState, ThreadedAdapterServer
from communication.client import GameAdapterClient


class FakeBackend:
    def __init__(self, status: str = "injected") -> None:
        self.status = status
        self.calls: list[str] = []

    def execute(self, ability: str) -> tuple[str, str]:
        self.calls.append(ability)
        return self.status, f"fake {ability}"


@contextmanager
def running_server(state: AdapterState):
    server = ThreadedAdapterServer(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def raw_exchange(address, payload: bytes) -> dict:
    with socket.create_connection(address, timeout=2.0) as connection:
        connection.sendall(payload)
        data = b""
        while not data.endswith(b"\n"):
            chunk = connection.recv(1024)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode("utf-8"))


def test_client_server_ack_and_duplicate_protection() -> None:
    backend = FakeBackend()
    state = AdapterState(backend)
    with running_server(state) as (host, port):
        client = GameAdapterClient(host=host, port=port)
        first = client.send_force_push()
        assert first.ok and first.delivered
        assert first.status == "injected"
        assert first.sequence == 1

        duplicate_message = {
            "type": "ABILITY_TRIGGER",
            "ability": "FORCE_PUSH",
            "hand": "RIGHT",
            "session_id": client.session_id,
            "sequence": 1,
        }
        status, _ = state.process(duplicate_message)
        assert status == "duplicate"
        assert backend.calls == ["FORCE_PUSH"]  # a duplicata não chegou ao backend


def test_wrong_token_is_rejected_and_backend_not_called() -> None:
    backend = FakeBackend()
    with running_server(AdapterState(backend, auth_token="segredo")) as (host, port):
        bad = GameAdapterClient(host=host, port=port, auth_token="errado").send_force_push()
        assert bad.delivered and not bad.ok
        assert bad.status == "rejected"
        missing = GameAdapterClient(host=host, port=port).send_force_push()
        assert missing.status == "rejected"
        assert backend.calls == []

        good = GameAdapterClient(host=host, port=port, auth_token="segredo").send_force_push()
        assert good.ok and good.status == "injected"
        assert backend.calls == ["FORCE_PUSH"]


def test_blocked_status_is_delivered_but_not_ok() -> None:
    with running_server(AdapterState(FakeBackend("blocked_not_focused"))) as (host, port):
        result = GameAdapterClient(host=host, port=port).send_force_push()
        assert result.delivered is True
        assert result.ok is False
        assert result.status == "blocked_not_focused"


def test_invalid_json_gets_rejected_ack() -> None:
    with running_server(AdapterState(FakeBackend())) as address:
        ack = raw_exchange(address, b"isto nao e json\n")
        assert ack["type"] == "ACK"
        assert ack["status"] == "rejected"


def test_unsupported_ability_and_hand_are_rejected() -> None:
    state = AdapterState(FakeBackend())
    base = {"type": "ABILITY_TRIGGER", "ability": "FORCE_PUSH", "hand": "RIGHT",
            "session_id": "s", "sequence": 1}
    assert state.process({**base, "ability": "FORCE_PULL"})[0] == "rejected"
    assert state.process({**base, "hand": "LEFT"})[0] == "rejected"
    assert state.process({**base, "sequence": 0})[0] == "rejected"
    assert state.process({**base, "sequence": True})[0] == "rejected"
    assert state.process({**base, "session_id": ""})[0] == "rejected"


def test_backend_exception_becomes_failed_status() -> None:
    class Boom:
        def execute(self, ability: str) -> tuple[str, str]:
            raise RuntimeError("explodiu")

    state = AdapterState(Boom())
    status, detail = state.process({"type": "ABILITY_TRIGGER", "ability": "FORCE_PUSH",
                                    "hand": "RIGHT", "session_id": "s", "sequence": 1})
    assert status == "failed"
    assert "explodiu" in detail


def test_client_reports_unavailable_when_server_is_down() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    result = GameAdapterClient(port=port, timeout=0.3).send_force_push()
    assert result.delivered is False
    assert result.ok is False
    assert result.status == "unavailable"
