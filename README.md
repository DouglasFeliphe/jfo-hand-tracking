# JFO Hand Tracking — Phase 4

Reconhece o gesto de Force Push com a mão direita, envia um comando JSON por TCP (`127.0.0.1:8765`) ao adaptador, e o adaptador pressiona a tecla **2** no Jedi: Fallen Order.

> **Importante:** no modo `keyboard` o adaptador envia teclas reais ao Windows. Ele só injeta quando a janela em primeiro plano contém o texto de `game.window_title_contains`. Comece sempre no modo `dry_run`.

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

## Configuração (`config/settings.json`, seção `game`)

| Campo | Descrição |
|---|---|
| `mode` | `dry_run` (só confirma) ou `keyboard` (injeta teclas). Pode ser sobrescrito com `--mode`. |
| `window_title_contains` | Trecho do título da janela que precisa estar em foco. Padrão: `Jedi`. |
| `auth_token` | Segredo compartilhado entre cliente e adaptador. **Obrigatório trocar** para usar `keyboard`. |
| `min_interval_seconds` | Intervalo mínimo entre injeções. |
| `bindings.FORCE_PUSH` | `keys` (lista, pressionadas juntas) e `hold_ms` (tempo da tecla pressionada). Padrão: tecla `2`, 80 ms. |

Gere um token:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(16))"
```

Teclas aceitas em `keys`: `0`–`9`, `Q W E R T F G`, `LSHIFT`, `LCTRL`, `SPACE` (veja `SCANCODES` em `adapter/input_backend.py`). A tecla `2` é a da linha numérica do topo, não a do teclado numérico.

## Execução

Terminal 1 — adaptador:

```powershell
.\.venv\Scripts\python.exe -m adapter.server
```

Terminal 2 — webcam e reconhecimento:

```powershell
.\.venv\Scripts\python.exe main.py
```

Pressione `Q` na janela da webcam para sair e `Ctrl+C` no terminal do adaptador.

Se o jogo rodar como administrador, o adaptador também precisa rodar como administrador (UIPI).

## Roteiro de validação

1. `mode: dry_run`: o painel mostra `ADAPTER: DRY_RUN` ao disparar o gesto.
2. `mode: keyboard`, `window_title_contains: "Bloco de Notas"` (ou `Notepad`) e Bloco de Notas em foco: o gesto digita `2`.
3. Tire o foco do Bloco de Notas: o painel mostra `BLOCKED_NOT_FOCUSED` e nada é digitado.
4. Volte `window_title_contains` para `Jedi`, abra o jogo em janela ou janela sem borda, confira em *Opções → Controles* que Force Push é a tecla 2 e teste em uma área segura. A habilidade precisa estar desbloqueada e a barra de Força disponível.
5. Ajuste `cooldown_seconds`, `scale_trigger_ratio` e `z_trigger_delta` conforme os falsos positivos.

Obs.: ao clicar na janela da webcam, o foco sai do jogo e os comandos são bloqueados. Clique de volta no jogo antes de gesticular.

## Protocolo

Cada conexão TCP carrega uma mensagem JSON terminada por `\n`:

```json
{
  "type": "ABILITY_TRIGGER",
  "ability": "FORCE_PUSH",
  "hand": "RIGHT",
  "session_id": "UUID da execução do cliente",
  "sequence": 1,
  "token": "segredo compartilhado"
}
```

O ACK contém `type`, `status`, `session_id`, `sequence` e `message`. Status possíveis:

| Status | Significado |
|---|---|
| `injected` | Tecla enviada ao jogo. |
| `dry_run` | Recebido; nenhuma tecla enviada. |
| `duplicate` | `(session_id, sequence)` já visto; ignorado. |
| `blocked_not_focused` | A janela do jogo não está em primeiro plano. |
| `rate_limited` | Intervalo mínimo entre comandos não respeitado. |
| `failed` | Erro ao injetar (ex.: jogo como administrador). |
| `rejected` | Token, formato ou campos inválidos. |

Um ACK confirma que o adaptador respondeu. Só `injected` indica que a tecla foi enviada; o jogo ainda pode ignorá-la (habilidade bloqueada, sem Força, menu aberto).

## Testes automatizados

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Os testes não dependem do Windows nem de webcam: o `KeyboardBackend` é testado com as chamadas ao sistema simuladas.

## Estrutura

```text
jfo-hand-tracking/
├── adapter/
│   ├── input_backend.py   # DryRunBackend e KeyboardBackend (SendInput)
│   └── server.py
├── communication/
│   ├── client.py
│   └── async_sender.py    # envio em thread, sem travar o vídeo
├── hand_tracking/
├── tests/
├── config/settings.json
├── main.py
└── requirements.txt
```

## Limitações conhecidas

- A injeção é por teclado (`SendInput` com scancodes). Não há integração com UE4SS.
- Não há retorno do jogo: o adaptador não sabe se Force Push realmente foi executado.
- O reconhecedor usa escala 2D da palma como pista principal; girar a mão pode gerar falsos positivos ocasionais.
- O cliente abre uma conexão por evento, adequado à baixa frequência dos gestos.
