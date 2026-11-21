# JFO Hand Tracking — Phase 4

Reconhece gestos da mão direita e os transmite por TCP (`127.0.0.1:8765`) a um adaptador, que pressiona a tecla da habilidade no Jedi: Fallen Order. Enquanto o gesto é mantido, a tecla **continua pressionada**; ao terminá-lo, ela é solta.

| Habilidade              | Gesto                                                                                     | Tecla |
| ----------------------- | ----------------------------------------------------------------------------------------- | ----- |
| Empurrão (`FORCE_PUSH`) | Palma aberta parada e depois um avanço da mão para a câmera                               | `2`   |
| Lentidão (`FORCE_SLOW`) | Pinça (sinal de "OK"): polegar tocando o indicador, com médio, anelar e mínimo estendidos | `1`   |

Uma mão, um gesto por vez: enquanto o empurrão está sendo segurado, a pinça é ignorada.

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

| Campo                     | Descrição                                                                                                                                                                                                       |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hold_enabled`            | `false` desativa o segurar: a tecla é solta no quadro seguinte (toque).                                                                                                                                         |
| `hold_release_ratio`      | Escala da palma (relativa ao armamento) abaixo da qual a mão é considerada recuada. Padrão 1,04.                                                                                                                |
| `hold_release_seconds`    | Tempo que o fim da pose precisa durar para soltar (evita soltar por um quadro ruim).                                                                                                                            |
| `hold_lost_grace_seconds` | Tolerância a perda de rastreamento antes de soltar.                                                                                                                                                             |
| `pinch_exclusion_ratio`   | Polegar mais perto que isso (em larguras de palma) da ponta do indicador nunca conta como palma aberta. Mantém empurrão e pinça mutuamente exclusivos. Mantenha ≥ `pinch_open_ratio` da lentidão. `0` desativa. |

### `slow_gesture` (lentidão, pinça)

| Campo                                                             | Descrição                                                                                                           |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `enabled`                                                         | `false` desativa o gesto de lentidão.                                                                               |
| `pinch_close_ratio`                                               | Distância polegar–indicador (em larguras de palma) abaixo da qual a pinça começa. Padrão 0,28.                      |
| `pinch_open_ratio`                                                | Distância acima da qual a pinça é considerada desfeita (histerese). Padrão 0,40.                                    |
| `finger_extended_angle`                                           | Ângulo mínimo para médio, anelar e mínimo contarem como estendidos. Para manter a pinça, tolera 10° a menos.        |
| `stability_seconds`                                               | Tempo que a pinça precisa ficar estável para disparar (menor = mais rápido, mais disparos acidentais). Padrão 0,20. |
| `cooldown_seconds`                                                | Espera mínima antes de poder disparar de novo; a pinça também precisa ser desfeita.                                 |
| `hold_enabled`, `hold_release_seconds`, `hold_lost_grace_seconds` | Iguais aos do empurrão.                                                                                             |

### `game`

| Campo                       | Descrição                                                                                                                                           |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mode`                      | `dry_run` (só confirma) ou `keyboard` (injeta teclas). Pode ser sobrescrito com `--mode`.                                                           |
| `window_title_contains`     | Trecho do título da janela que precisa estar em foco.                                                                                               |
| `auth_token`                | Segredo compartilhado. **Obrigatório trocar** para usar `keyboard`.                                                                                 |
| `min_interval_seconds`      | Intervalo mínimo entre dois pressionamentos da mesma habilidade.                                                                                    |
| `heartbeat_timeout_seconds` | Soltura automática sem heartbeat.                                                                                                                   |
| `max_hold_seconds`          | Tempo máximo contínuo com a tecla pressionada.                                                                                                      |
| `bindings.<HABILIDADE>`     | `keys` (pressionadas juntas), `hold_ms` (tempo mínimo pressionada) e `allow_hold` (`true` mantém até o STOP; `false` solta sozinha após `hold_ms`). |

`communication.heartbeat_seconds` define o intervalo dos heartbeats (0,15 s).

Gere um token: `.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(16))"`

Teclas aceitas em `keys`: `0`–`9`, `Q W E R T F G`, `LSHIFT`, `LCTRL`, `SPACE` (veja `SCANCODES` em `adapter/input_backend.py`). `2` é a tecla da linha numérica do topo, não a do teclado numérico. Duas habilidades não podem compartilhar a mesma tecla.

## Lentidão (pinça)

A lentidão usa a tecla `1`. Segundo a wiki do jogo, um toque ativa a lentidão e segurar dá um efeito maior, então o binding usa `allow_hold: true`: uma pinça curta vira um toque e mantê-la segura a tecla.

- **Disparo:** pinça estável por `stability_seconds` (0,2 s) → START.
- **Manter:** heartbeats enquanto a pinça durar.
- **Soltar:** pinça desfeita por 0,15 s, dedos dobrados ou mão perdida → STOP.
- Não usa escala nem profundidade (z), só distâncias e ângulos no plano da imagem.
- Evite punho fechado para outros gestos: ele é a pose que rearma o empurrão.

## Adicionando outras habilidades (puxão...)

1. **Binding:** em `game.bindings`, por exemplo `"FORCE_PULL": { "keys": ["3"], "hold_ms": 80, "allow_hold": false }`. O adaptador aceita a habilidade automaticamente. O puxão é um toque, então `allow_hold: false`.
2. **Gesto:** crie um reconhecedor com o mesmo contrato (`triggered`, `hold_released`, `holding`), como `GestureRecognizer` e `PinchRecognizer`.
3. **Ligação:** em `main.py`, crie a constante da habilidade e chame `dispatch(sender, ABILITY, result)` com o resultado do reconhecedor. Passe `suppressed=...` para ele esperar os outros gestos terminarem. O envio já aceita várias habilidades ao mesmo tempo.

Duas habilidades não podem compartilhar a mesma tecla.

## Roteiro de validação

1. `mode: dry_run`: ao empurrar, o painel mostra `ADAPTER: DRY_RUN`; ao fechar a mão, `ADAPTER: RELEASED`.
2. `mode: keyboard` e `window_title_contains: "Bloco de Notas"`: empurre e mantenha a mão aberta e estendida. O Bloco de Notas deve repetir `2` (repetição de tecla do Windows enquanto segura). Feche a mão e a repetição para.
3. Durante o segurar, clique em outra janela: a tecla deve ser solta (perda de foco).
4. Durante o segurar, feche a janela da webcam à força: em até 0,5 s a tecla deve ser solta (watchdog).
5. Lentidão: no modo `dry_run`, faça a pinça. O painel mostra `SLOW: HOLDING` e `ADAPTER: DRY_RUN (SLOW)`; ao abrir a pinça, `RELEASED (SLOW)`. No Bloco de Notas, segurar a pinça repete `1`.
6. Confirme que os gestos não se confundem: a pinça nunca arma o empurrão e a palma aberta nunca dispara a lentidão.
7. Volte `window_title_contains` para `Jedi` e teste no jogo, numa área segura.

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

| Status                | Significado                                                |
| --------------------- | ---------------------------------------------------------- |
| `injected`            | START: tecla pressionada.                                  |
| `dry_run`             | START em modo de teste; nenhuma tecla enviada.             |
| `held`                | HEARTBEAT: tecla mantida.                                  |
| `released`            | STOP: tecla solta.                                         |
| `not_active`          | A tecla já estava solta (por exemplo, soltura automática). |
| `already_active`      | START com a habilidade já pressionada.                     |
| `duplicate`           | Mensagem já recebida; ignorada.                            |
| `blocked_not_focused` | A janela do jogo não está em primeiro plano.               |
| `rate_limited`        | Intervalo mínimo entre pressionamentos não respeitado.     |
| `failed`              | Erro ao injetar (ex.: jogo como administrador).            |
| `rejected`            | Token, formato ou campos inválidos.                        |

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
├── hand_tracking/         # câmera, detector, gestos (empurrão), pinch (lentidão), landmarks
├── tests/
├── config/settings.json
├── main.py
└── requirements.txt
```

## Limitações conhecidas

- A injeção é por teclado (`SendInput` com scancodes). Não há integração com UE4SS.
- Não há retorno do jogo: o adaptador não sabe se a habilidade realmente foi executada.
- O reconhecedor do empurrão usa a escala 2D da palma como pista principal; girar a mão pode gerar falsos positivos ocasionais.
- A pinça pode ser mais difícil de detectar com a mão de lado ou muito longe da câmera; ajuste `pinch_close_ratio` e `stability_seconds`.
- Durante o segurar, se o reconhecimento de "palma aberta" falhar por mais de `hold_release_seconds` (dedos dobrando no movimento), a tecla é solta.
