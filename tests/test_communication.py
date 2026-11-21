from __future__ import annotations

import threading

from adapter.server import AdapterState, ThreadedAdapterServer
from communication.client import GameAdapterClient


def test_client_server_ack_and_duplicate_protection() -> None:
    state = AdapterState()
    server = ThreadedAdapterServer(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        client = GameAdapterClient(host=host, port=port)
        first = client.send_force_push()
        assert first.ok
        assert first.status == "received"
        assert first.sequence == 1

        # Replaying the same identity/sequence is deduplicated by adapter state.
        duplicate_message = {
            "type": "ABILITY_TRIGGER",
            "ability": "FORCE_PUSH",
            "hand": "RIGHT",
            "session_id": client.session_id,
            "sequence": 1,
        }
        status, _ = state.process(duplicate_message)
        assert status == "duplicate"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
