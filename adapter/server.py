from __future__ import annotations

import argparse
import hmac
import json
import socketserver
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from adapter.input_backend import DryRunBackend, InputBackend, KeyboardBackend

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "settings.json"
DEFAULT_ABILITIES = frozenset({"FORCE_PUSH"})
MESSAGE_TYPES = {"ABILITY_START", "ABILITY_STOP", "ABILITY_HEARTBEAT"}
HANDS = {"RIGHT", "LEFT"}
PLACEHOLDER_TOKEN = "troque-este-valor"
MAX_LINE_BYTES = 8192


class AdapterState:
    def __init__(
        self,
        backend: InputBackend | None = None,
        auth_token: str | None = None,
        dedupe_limit: int = 2048,
        supported_abilities: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.backend: InputBackend = backend or DryRunBackend()
        self.auth_token = auth_token or None
        self.dedupe_limit = dedupe_limit
        self.supported_abilities = frozenset(supported_abilities or DEFAULT_ABILITIES)
        self._seen: OrderedDict[tuple[str, int], None] = OrderedDict()
        self._lock = threading.Lock()

    def _token_ok(self, message: dict[str, Any]) -> bool:
        if not self.auth_token:
            return True
        provided = message.get("token")
        if not isinstance(provided, str):
            return False
        return hmac.compare_digest(provided.encode("utf-8"), self.auth_token.encode("utf-8"))

    def process(self, message: dict[str, Any]) -> tuple[str, str]:
        if not self._token_ok(message):
            return "rejected", "Token inválido."
        message_type = message.get("type")
        if message_type not in MESSAGE_TYPES:
            return "rejected", "Tipo de mensagem não suportado."
        ability = message.get("ability")
        if ability not in self.supported_abilities:
            return "rejected", "Habilidade não suportada."
        if message.get("hand") not in HANDS:
            return "rejected", "Mão inválida."
        session_id = message.get("session_id")
        sequence = message.get("sequence")
        if not isinstance(session_id, str) or not session_id or len(session_id) > 64:
            return "rejected", "session_id inválido."
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            return "rejected", "sequence deve ser um inteiro positivo."

        # Heartbeat é idempotente: não entra na janela de deduplicação.
        if message_type != "ABILITY_HEARTBEAT":
            key = (f"{message_type}:{session_id}", sequence)
            with self._lock:
                if key in self._seen:
                    return "duplicate", "Comando já recebido; não será processado novamente."
                self._seen[key] = None
                while len(self._seen) > self.dedupe_limit:
                    self._seen.popitem(last=False)

        try:
            if message_type == "ABILITY_START":
                return self.backend.press(ability)
            if message_type == "ABILITY_STOP":
                return self.backend.release(ability)
            return self.backend.heartbeat(ability)
        except Exception as error:  # o backend nunca deve derrubar o servidor
            return "failed", f"Erro no backend: {error}"

    def close(self) -> None:
        self.backend.close()


class RequestHandler(socketserver.StreamRequestHandler):
    def _reply(self, status: str, detail: str, message: dict[str, Any] | None = None) -> None:
        message = message or {}
        ack = {
            "type": "ACK",
            "status": status,
            "session_id": message.get("session_id"),
            "sequence": message.get("sequence"),
            "message": detail,
        }
        self.wfile.write((json.dumps(ack, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()

    def handle(self) -> None:
        self.request.settimeout(2.0)
        try:
            raw = self.rfile.readline(MAX_LINE_BYTES + 1)
            if not raw:
                return
            if len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
                self._reply("rejected", "Mensagem grande demais ou sem terminador de linha.")
                print("[ADAPTER] Mensagem rejeitada: tamanho/terminador inválido.")
                return
            try:
                message = json.loads(raw.decode("utf-8"))
                if not isinstance(message, dict):
                    raise ValueError("A mensagem precisa ser um objeto JSON.")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                self._reply("rejected", f"Mensagem inválida: {error}")
                print(f"[ADAPTER] Mensagem inválida: {error}")
                return

            status, detail = self.server.state.process(message)  # type: ignore[attr-defined]
            self._reply(status, detail, message)
            # Heartbeats saudáveis são frequentes; não polui o log.
            if not (message.get("type") == "ABILITY_HEARTBEAT" and status == "held"):
                print(f"[ADAPTER] {message.get('type')} {message.get('ability')} "
                      f"seq={message.get('sequence')} -> {status} | {detail}")
        except OSError as error:
            print(f"[ADAPTER] Erro de conexão: {error}")


class ThreadedAdapterServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: AdapterState) -> None:
        self.state = state
        super().__init__(address, RequestHandler)


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def main() -> int:
    config = load_config()
    game = config.get("game", {})
    communication = config.get("communication", {})

    parser = argparse.ArgumentParser(description="Adaptador TCP local para JFO Hand Tracking")
    parser.add_argument("--host", default=communication.get("host", "127.0.0.1"),
                        help="Por segurança, use localhost (padrão: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=communication.get("port", 8765))
    parser.add_argument("--mode", choices=("dry_run", "keyboard"), default=game.get("mode", "dry_run"),
                        help="dry_run apenas confirma; keyboard injeta teclas no jogo (Windows).")
    args = parser.parse_args()

    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("O adaptador deve escutar somente em localhost.")

    token = game.get("auth_token") or None
    bindings = game.get("bindings", {})
    backend: InputBackend
    if args.mode == "keyboard":
        if sys.platform != "win32":
            parser.error("O modo keyboard só funciona no Windows.")
        if not token or token == PLACEHOLDER_TOKEN:
            parser.error("Defina um game.auth_token próprio em config/settings.json antes de usar o modo keyboard.")
        try:
            backend = KeyboardBackend(
                bindings=bindings,
                window_title_contains=game.get("window_title_contains", "Jedi"),
                min_interval=float(game.get("min_interval_seconds", 0.5)),
                heartbeat_timeout=float(game.get("heartbeat_timeout_seconds", 0.5)),
                max_hold_seconds=float(game.get("max_hold_seconds", 8.0)),
            )
        except (ValueError, RuntimeError) as error:
            parser.error(f"Configuração de teclado inválida: {error}")
    else:
        backend = DryRunBackend()

    state = AdapterState(backend, auth_token=token, supported_abilities=set(bindings) or None)
    server = ThreadedAdapterServer((args.host, args.port), state)
    print(f"[ADAPTER] Escutando em {args.host}:{args.port} | modo={args.mode}")
    if args.mode == "keyboard":
        print(f"[ADAPTER] ATENÇÃO: teclas serão enviadas à janela que contém '{game.get('window_title_contains', 'Jedi')}'.")
        print(f"[ADAPTER] Soltura automática: sem heartbeat por {game.get('heartbeat_timeout_seconds', 0.5)}s, "
              f"perda de foco ou {game.get('max_hold_seconds', 8.0)}s no máximo.")
    else:
        print("[ADAPTER] dry_run: recebe e confirma comandos, mas NÃO envia teclas.")
    print("[ADAPTER] Pressione Ctrl+C para encerrar.")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\n[ADAPTER] Encerrando...")
    finally:
        server.shutdown()
        server.server_close()
        state.close()  # solta qualquer tecla ainda pressionada
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
