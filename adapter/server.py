from __future__ import annotations

import argparse
import json
import socketserver
import threading
import time
from collections import OrderedDict
from typing import Any


class AdapterState:
    def __init__(self, dedupe_limit: int = 2048) -> None:
        self._seen: OrderedDict[tuple[str, int], float] = OrderedDict()
        self._lock = threading.Lock()
        self.dedupe_limit = dedupe_limit

    def process(self, message: dict[str, Any]) -> tuple[str, str]:
        if message.get("type") != "ABILITY_TRIGGER":
            return "rejected", "Tipo de mensagem não suportado."
        if message.get("ability") != "FORCE_PUSH":
            return "rejected", "Habilidade não suportada pelo adaptador de teste."
        if message.get("hand") != "RIGHT":
            return "rejected", "A POC aceita somente a mão direita."
        session_id = message.get("session_id")
        sequence = message.get("sequence")
        if not isinstance(session_id, str) or not session_id or len(session_id) > 64:
            return "rejected", "session_id inválido."
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            return "rejected", "sequence deve ser um inteiro positivo."

        key = (session_id, sequence)
        with self._lock:
            if key in self._seen:
                return "duplicate", "Comando já recebido; não será processado novamente."
            self._seen[key] = time.monotonic()
            while len(self._seen) > self.dedupe_limit:
                self._seen.popitem(last=False)
        return "received", "Comando recebido pelo adaptador de teste; nenhuma ação foi executada no jogo."


class RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(2.0)
        try:
            raw = self.rfile.readline(8193)
            if not raw or len(raw) > 8192 or not raw.endswith(b"\n"):
                return
            message = json.loads(raw.decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError("A mensagem precisa ser um objeto JSON.")
            status, detail = self.server.state.process(message)  # type: ignore[attr-defined]
            ack = {
                "type": "ACK",
                "status": status,
                "session_id": message.get("session_id"),
                "sequence": message.get("sequence"),
                "message": detail,
            }
            self.wfile.write((json.dumps(ack, ensure_ascii=False) + "\n").encode("utf-8"))
            if status == "received":
                print(f"[ADAPTER] {message['ability']} recebido | mão={message['hand']} | seq={message['sequence']}")
            elif status == "duplicate":
                print(f"[ADAPTER] Duplicata ignorada | seq={message.get('sequence')}")
            else:
                print(f"[ADAPTER] Comando rejeitado: {detail}")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            print(f"[ADAPTER] Mensagem inválida: {error}")


class ThreadedAdapterServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: AdapterState) -> None:
        self.state = state
        super().__init__(address, RequestHandler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Adaptador TCP local de teste para JFO Hand Tracking")
    parser.add_argument("--host", default="127.0.0.1", help="Por segurança, use localhost (padrão: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("O adaptador de desenvolvimento deve escutar somente em localhost.")
    server = ThreadedAdapterServer((args.host, args.port), AdapterState())
    print(f"[ADAPTER] Escutando em {args.host}:{args.port}")
    print("[ADAPTER] Modo de teste: recebe e confirma comandos, mas NÃO controla o jogo.")
    print("[ADAPTER] Pressione Ctrl+C para encerrar.")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\n[ADAPTER] Encerrando...")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
