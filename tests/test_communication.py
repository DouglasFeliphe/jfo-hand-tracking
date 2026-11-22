from __future__ import annotations

import json
import socket
import threading
import time
from contextlib import contextmanager

from adapter.server import AdapterState, ThreadedAdapterServer
from communication.async_sender import AsyncSender
from communication.client import GameAdapterClient


class FakeBackend:
    def __init__(self, press_status: str = "injected") -> None:
        self.press_status = press_status
        self.calls: list[tuple[str, str]] = []
        self.active: set[str] = set()

    def press(self, ability: str) -> tuple[str, str]:
        self.calls.append(("press", ability))
        if self.press_status == "injected":
            self.active.add(ability)
        return self.press_status, "fake press"

    def release(self, ability: str) -> tuple[str, str]:
        self.calls.append(("release", ability))
        was_active = ability in self.active
        self.active.discard(ability)
        return ("released" if was_active else "not_active"), "fake release"

    def heartbeat(self, ability: str) -> tuple[str, str]:
        self.calls.append(("heartbeat", ability))
        return ("held" if ability in self.active else "not_active"), "fake heartbeat"

    def close(self) -> None:
        self.calls.append(("close", ""))

    def count(self, kind: str) -> int:
        return sum(1 for call in self.calls if call[0] == kind)


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


def wait_until(condition, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def message(message_type: str, sequence: int, **extra) -> dict:
    return {"type": message_type, "ability": "FORCE_PUSH", "hand": "RIGHT",
            "session_id": "sessao", "sequence": sequence, **extra}


def test_start_stop_roundtrip_and_duplicate_protection() -> None:
    backend = FakeBackend()
    state = AdapterState(backend)
    with running_server(state) as (host, port):
        client = GameAdapterClient(host=host, port=port)
        start = client.send_start()
        assert start.ok and start.delivered
        assert start.status == "injected"
        assert start.kind == "START"
        assert start.ability == "FORCE_PUSH"
        assert start.sequence == 1

        replay = {"type": "ABILITY_START", "ability": "FORCE_PUSH", "hand": "RIGHT",
                  "session_id": client.session_id, "sequence": 1}
        assert state.process(replay)[0] == "duplicate"
        assert backend.count("press") == 1  # a duplicata não chegou ao backend

        stop = client.send_stop()
        assert stop.ok and stop.status == "released"
        assert backend.count("release") == 1


def test_heartbeat_is_not_deduplicated() -> None:
    state = AdapterState(FakeBackend())
    assert state.process(message("ABILITY_START", 1))[0] == "injected"
    assert state.process(message("ABILITY_HEARTBEAT", 2))[0] == "held"
    assert state.process(message("ABILITY_HEARTBEAT", 2))[0] == "held"


def test_heartbeat_reports_not_active_after_release() -> None:
    with running_server(AdapterState(FakeBackend())) as (host, port):
        client = GameAdapterClient(host=host, port=port)
        client.send_start()
        client.send_stop()
        beat = client.send_heartbeat()
        assert beat.delivered and not beat.ok
        assert beat.status == "not_active"


def test_wrong_token_is_rejected_and_backend_not_called() -> None:
    backend = FakeBackend()
    with running_server(AdapterState(backend, auth_token="segredo")) as (host, port):
        bad = GameAdapterClient(host=host, port=port, auth_token="errado").send_start()
        assert bad.delivered and not bad.ok
        assert bad.status == "rejected"
        missing = GameAdapterClient(host=host, port=port).send_start()
        assert missing.status == "rejected"
        assert backend.calls == []

        good = GameAdapterClient(host=host, port=port, auth_token="segredo").send_start()
        assert good.ok and good.status == "injected"


def test_blocked_status_is_delivered_but_not_ok() -> None:
    with running_server(AdapterState(FakeBackend("blocked_not_focused"))) as (host, port):
        result = GameAdapterClient(host=host, port=port).send_start()
        assert result.delivered is True
        assert result.ok is False
        assert result.status == "blocked_not_focused"


def test_invalid_json_gets_rejected_ack() -> None:
    with running_server(AdapterState(FakeBackend())) as address:
        ack = raw_exchange(address, b"isto nao e json\n")
        assert ack["type"] == "ACK"
        assert ack["status"] == "rejected"


def test_invalid_fields_are_rejected() -> None:
    state = AdapterState(FakeBackend())
    base = message("ABILITY_START", 1)
    assert state.process({**base, "type": "ABILITY_TRIGGER"})[0] == "rejected"
    assert state.process({**base, "ability": "FORCE_PULL"})[0] == "rejected"
    assert state.process({**base, "hand": "FOOT"})[0] == "rejected"
    assert state.process({**base, "sequence": 0})[0] == "rejected"
    assert state.process({**base, "sequence": True})[0] == "rejected"
    assert state.process({**base, "session_id": ""})[0] == "rejected"


def test_slow_ability_roundtrip_through_client() -> None:
    backend = FakeBackend()
    state = AdapterState(backend, supported_abilities={"FORCE_PUSH", "FORCE_SLOW"})
    with running_server(state) as (host, port):
        client = GameAdapterClient(host=host, port=port)
        start = client.send_start("FORCE_SLOW", "LEFT")
        assert start.ok and start.ability == "FORCE_SLOW"
        assert client.send_heartbeat("FORCE_SLOW", "LEFT").status == "held"
        assert client.send_stop("FORCE_SLOW", "LEFT").status == "released"
        assert backend.calls[0] == ("press", "FORCE_SLOW")


def test_new_ability_is_accepted_only_when_configured() -> None:
    state = AdapterState(FakeBackend(), supported_abilities={"FORCE_PUSH", "FORCE_SLOW"})
    slow = {**message("ABILITY_START", 1), "ability": "FORCE_SLOW"}
    assert state.process(slow)[0] == "injected"
    pull = {**message("ABILITY_START", 2), "ability": "FORCE_PULL"}
    assert state.process(pull)[0] == "rejected"


def test_backend_exception_becomes_failed_status() -> None:
    class Boom(FakeBackend):
        def press(self, ability: str) -> tuple[str, str]:
            raise RuntimeError("explodiu")

    status, detail = AdapterState(Boom()).process(message("ABILITY_START", 1))
    assert status == "failed"
    assert "explodiu" in detail


def test_client_reports_unavailable_when_server_is_down() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    result = GameAdapterClient(port=port, timeout=0.3).send_start()
    assert result.delivered is False
    assert result.ok is False
    assert result.status == "unavailable"


def test_async_sender_start_heartbeats_then_stop() -> None:
    backend = FakeBackend()
    with running_server(AdapterState(backend)) as (host, port):
        sender = AsyncSender(GameAdapterClient(host=host, port=port), heartbeat_interval=0.03)
        sender.start()
        try:
            assert sender.start_ability("FORCE_PUSH")
            assert wait_until(lambda: backend.count("heartbeat") >= 2)
            assert sender.stop_ability("FORCE_PUSH")
            assert wait_until(lambda: backend.count("release") == 1)
            beats = backend.count("heartbeat")
            time.sleep(0.15)
            assert backend.count("heartbeat") == beats  # sem heartbeats depois do STOP
        finally:
            sender.close()


def test_async_sender_stops_heartbeats_when_adapter_released_key() -> None:
    backend = FakeBackend()
    with running_server(AdapterState(backend)) as (host, port):
        sender = AsyncSender(GameAdapterClient(host=host, port=port), heartbeat_interval=0.03)
        sender.start()
        try:
            sender.start_ability("FORCE_PUSH")
            assert wait_until(lambda: backend.count("heartbeat") >= 1)
            backend.active.clear()  # simula a soltura automática do watchdog
            assert wait_until(lambda: sender.last_result is not None and sender.last_result.status == "not_active")
            beats = backend.count("heartbeat")
            time.sleep(0.15)
            assert backend.count("heartbeat") == beats
        finally:
            sender.close()


def test_async_sender_retries_stop_when_adapter_is_unreachable() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    client = GameAdapterClient(port=port, timeout=0.2)
    sender = AsyncSender(client, heartbeat_interval=0.5)
    sender.start()
    try:
        assert sender.stop_ability("FORCE_PUSH")
        assert wait_until(lambda: client.sequence == 3)  # 3 tentativas de STOP
        assert wait_until(lambda: sender.last_result is not None)
        assert sender.last_result.status == "unavailable"
    finally:
        sender.close()


def test_async_sender_forwards_the_hand_for_each_ability() -> None:
    from communication.client import SendResult

    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def _result(self, kind: str, status: str, ability: str) -> SendResult:
            return SendResult(True, status, "", len(self.calls), True, kind, ability)

        def send_start(self, ability: str, hand: str = "RIGHT") -> SendResult:
            self.calls.append(("START", ability, hand))
            return self._result("START", "injected", ability)

        def send_stop(self, ability: str, hand: str = "RIGHT") -> SendResult:
            self.calls.append(("STOP", ability, hand))
            return self._result("STOP", "released", ability)

        def send_heartbeat(self, ability: str, hand: str = "RIGHT") -> SendResult:
            self.calls.append(("HEARTBEAT", ability, hand))
            return self._result("HEARTBEAT", "held", ability)

    client = RecordingClient()
    sender = AsyncSender(client, heartbeat_interval=0.03)  # type: ignore[arg-type]
    sender.start()
    try:
        sender.start_ability("FORCE_PUSH", "RIGHT")
        sender.start_ability("FORCE_SLOW", "LEFT")
        assert wait_until(lambda: ("HEARTBEAT", "FORCE_SLOW", "LEFT") in client.calls
                          and ("HEARTBEAT", "FORCE_PUSH", "RIGHT") in client.calls)
        sender.stop_ability("FORCE_SLOW", "LEFT")
        assert wait_until(lambda: ("STOP", "FORCE_SLOW", "LEFT") in client.calls)
    finally:
        sender.close()
    assert ("START", "FORCE_PUSH", "RIGHT") in client.calls
    assert ("START", "FORCE_SLOW", "LEFT") in client.calls
