# JFO Hand Tracking — Phase 4

Reconhece o gesto de Force Push com a mão direita e o transmite por TCP (`127.0.0.1:8765`) a um adaptador, que pressiona a tecla da habilidade no Jedi: Fallen Order. Depois do empurrão, mantendo a palma aberta e estendida, a tecla **continua pressionada**; ao fechar a mão ou recuá-la, ela é solta.

> **Importante:** no modo `keyboard` o adaptador envia teclas reais ao Windows, somente com a janela em primeiro plano contendo `game.window_title_contains`. Comece sempre no modo `dry_run`.

## Requisitos

- Windows 10/11 (o modo `keyboard` só funciona no Windows)
- Python 3.12
- Webcam

## Instalação

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Execução

Terminal 1 — adaptador: `.\.venv\Scripts\python.exe -m adapter.server`
Terminal 2 — webcam: `.\.venv\Scripts\python.exe main.py`

Pressione `Q` na janela da webcam para sair e `Ctrl+C` no adaptador. Ambos soltam qualquer tecla pressionada ao encerrar.

## Como funciona o "segurar"

```text
empurrão detectado ──► START  (tecla desce)
mão aberta e estendida ──► HEARTBEAT a cada 0,15 s (mantém a tecla)
fechar a mão / recuar / perder a mão ──► STOP (tecla sobe)
```

- **Sem atraso extra:** a tecla desce no instante do empurrão. Um gesto rápido vira um toque, porque a tecla fica pressionada pelo menos `hold_ms`.
- **Soltura automática no adaptador** (contra tecla presa). A tecla é solta se:
  - não chegar heartbeat por `heartbeat_timeout_seconds` (0,5 s);
  - a janela do jogo perder o foco;
  - passar de `max_hold_seconds` (8 s);
  - o adaptador for encerrado.
- O cliente reenvia o STOP até 3 vezes se a comunicação falhar.

## Configuração (`config/settings.json`)

### `gestures` (segurar)

| Campo | Descrição |
|---|---|
| `hold_enabled` | `false` desativa o segurar: a tecla é solta no quadro seguinte (toque). |
| `hold_release_ratio` | Escala da palma (relativa ao armamento) abaixo da qual a mão é considerada recuada. Padrão 1,04. |
| `hold_release_seconds` | Tempo que o fim da pose precisa durar para soltar (evita soltar por um quadro ruim). |
| `hold_lost_grace_seconds` | Tolerância a perda de rastreamento antes de soltar. |

### `game`

| Campo | Descrição |
|---|---|
| `mode` | `dry_run` (só confirma) ou `keyboard` (injeta teclas). Pode ser sobrescrito com `--mode`. |
| `window_title_contains` | Trecho do título da janela que precisa estar em foco. |
| `auth_token` | Segredo compartilhado. **Obrigatório trocar** para usar `keyboard`. |
| `min_interval_seconds` | Intervalo mínimo entre dois pressionamentos da mesma habilidade. |
| `heartbeat_timeout_seconds` | Soltura automática sem heartbeat. |
| `max_hold_seconds` | Tempo máximo contínuo com a tecla pressionada. |
| `bindings.<HABILIDADE>` | `keys` (pressionadas juntas), `hold_ms` (tempo mínimo pressionada) e `allow_hold` (`true` mantém até o STOP; `false` solta sozinha após `hold_ms`). |

`communication.heartbeat_seconds` define o intervalo dos heartbeats (0,15 s).

Gere um token: `.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(16))"`

Teclas aceitas em `keys`: `0`–`9`, `Q W E R T F G`, `LSHIFT`, `LCTRL`, `SPACE` (veja `SCANCODES` em `adapter/input_backend.py`). `2` é a tecla da linha numérica do topo, não a do teclado numérico. Duas habilidades não podem compartilhar a mesma tecla.

## Adicionando outras habilidades (lentidão, puxão...)

1. **Binding:** em `game.bindings`, por exemplo `"FORCE_SLOW": { "keys": ["1"], "hold_ms": 80, "allow_hold": true }`. O adaptador passa a aceitar a habilidade automaticamente.
2. **Gesto:** crie um reconhecedor para o novo gesto (ou reaproveite `GestureRecognizer` com outros parâmetros). Ele deve produzir `triggered` e `hold_released`, como o atual.
3. **Ligação:** em `main.py`, chame `sender.start_ability("FORCE_SLOW")` no `triggered` e `sender.stop_ability("FORCE_SLOW")` no `hold_released`. O envio já aceita várias habilidades ao mesmo tempo e envia heartbeat para cada uma.

Hoje o `main.py` usa a constante `ABILITY = "FORCE_PUSH"` para o gesto atual.

## Roteiro de validação

1. `mode: dry_run`: ao empurrar, o painel mostra `ADAPTER: DRY_RUN`; ao fechar a mão, `ADAPTER: RELEASED`.
2. `mode: keyboard` e `window_title_contains: "Bloco de Notas"`: empurre e mantenha a mão aberta e estendida. O Bloco de Notas deve repetir `2` (repetição de tecla do Windows enquanto segura). Feche a mão e a repetição para.
3. Durante o segurar, clique em outra janela: a tecla deve ser solta (perda de foco).
4. Durante o segurar, feche a janela da webcam à força: em até 0,5 s a tecla deve ser solta (watchdog).
5. Volte `window_title_contains` para `Jedi` e teste no jogo, numa área segura.

Se o jogo rodar como administrador, o adaptador também precisa rodar como administrador (UIPI).

## Protocolo

Cada conexão TCP carrega uma mensagem JSON terminada por `\n`:

```json
{
  "type": "ABILITY_START",
  "ability": "FORCE_PUSH",
  "hand": "RIGHT",
  "session_id": "UUID da execução do cliente",
  "sequence": 1,
  "token": "segredo compartilhado"
}
```

`type` é `ABILITY_START`, `ABILITY_STOP` ou `ABILITY_HEARTBEAT`. START e STOP são deduplicados por `(tipo, session_id, sequence)`; heartbeats não. O ACK contém `type`, `status`, `session_id`, `sequence` e `message`.

| Status | Significado |
|---|---|
| `injected` | START: tecla pressionada. |
| `dry_run` | START em modo de teste; nenhuma tecla enviada. |
| `held` | HEARTBEAT: tecla mantida. |
| `released` | STOP: tecla solta. |
| `not_active` | A tecla já estava solta (por exemplo, soltura automática). |
| `already_active` | START com a habilidade já pressionada. |
| `duplicate` | Mensagem já recebida; ignorada. |
| `blocked_not_focused` | A janela do jogo não está em primeiro plano. |
| `rate_limited` | Intervalo mínimo entre pressionamentos não respeitado. |
| `failed` | Erro ao injetar (ex.: jogo como administrador). |
| `rejected` | Token, formato ou campos inválidos. |

## Testes automatizados

`.\.venv\Scripts\python.exe -m pytest -q`

Não dependem do Windows nem de webcam: o `KeyboardBackend` é testado com foco, teclas e relógio simulados.

## Estrutura

```text
jfo-hand-tracking/
├── adapter/
│   ├── input_backend.py   # DryRunBackend e KeyboardBackend (SendInput + watchdog)
│   └── server.py
├── communication/
│   ├── client.py
│   └── async_sender.py    # envio em thread, heartbeats e STOP com reenvio
├── hand_tracking/         # câmera, detector, gestos (estado HOLDING), landmarks
├── tests/
├── config/settings.json
├── main.py
└── requirements.txt
```

## Limitações conhecidas

- A injeção é por teclado (`SendInput` com scancodes). Não há integração com UE4SS.
- Não há retorno do jogo: o adaptador não sabe se a habilidade realmente foi executada.
- O reconhecedor usa a escala 2D da palma como pista principal; girar a mão pode gerar falsos positivos ocasionais.
- Durante o segurar, se o reconhecimento de "palma aberta" falhar por mais de `hold_release_seconds` (dedos dobrando no movimento), a tecla é solta.
