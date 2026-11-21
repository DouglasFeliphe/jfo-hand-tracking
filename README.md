# JFO Hand Tracking — Phase 3

POC local para reconhecer o gesto de Force Push com a mão direita e transmitir um comando JSON ao adaptador de teste por TCP em `127.0.0.1:8765`.

> **Importante:** o adaptador desta fase apenas recebe e confirma mensagens. Ele não envia teclas, não injeta comandos e não executa ações dentro de Jedi: Fallen Order.

## Requisitos

- Windows 10/11
- Python 3.12
- Webcam

## Instalação

Na pasta do projeto:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Se você já possui o ambiente virtual da Fase 2, pode reutilizá-lo.

## Execução

Abra **dois terminais** na pasta do projeto.

Terminal 1 — iniciar o adaptador TCP de teste:

```powershell
.\.venv\Scripts\python.exe -m adapter.server
```

Terminal 2 — iniciar a webcam e o reconhecimento:

```powershell
.\.venv\Scripts\python.exe main.py
```

Quando o gesto FORCE_PUSH for confirmado, o Python enviará uma mensagem ao adaptador. O adaptador responderá com um ACK contendo o mesmo `session_id` e `sequence`. A janela mostrará `ADAPTER: ACK RECEIVED` quando a confirmação for válida.

Pressione `Q` na janela da webcam para encerrar. Use `Ctrl+C` no terminal do adaptador para encerrá-lo.

## Protocolo

Cada conexão TCP carrega uma mensagem JSON terminada por `\\n`:

```json
{
  "type": "ABILITY_TRIGGER",
  "ability": "FORCE_PUSH",
  "hand": "RIGHT",
  "session_id": "UUID da execução do cliente",
  "sequence": 1
}
```

O ACK contém `type`, `status`, `session_id`, `sequence` e `message`. O adaptador mantém uma janela de identificadores já recebidos para ignorar duplicatas.

O servidor escuta somente em localhost por padrão. A confirmação ACK significa **recebimento pelo adaptador**, não execução no jogo.

## Testes automatizados

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Estrutura

```text
jfo-hand-tracking/
├── adapter/
│   └── server.py
├── communication/
│   └── client.py
├── hand_tracking/
├── tests/
│   ├── test_gestures.py
│   └── test_communication.py
├── config/settings.json
├── main.py
└── requirements.txt
```

## Limitações conhecidas

- O adaptador é um simulador de integração para validar transporte, formato e confirmação.
- Não há integração com UE4SS nem com a API de entrada do jogo nesta fase.
- O cliente abre uma conexão por evento, uma escolha simples e adequada à baixa frequência dos gestos nesta POC.
