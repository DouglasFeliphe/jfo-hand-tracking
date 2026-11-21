# JFO Hand Tracking — Fase 1

POC de rastreamento da mão direita por webcam para o projeto Jedi: Fallen Order Hand Tracking.

## Requisitos

- Windows 10/11 (alvo inicial)
- Python 3.12 de 64 bits
- Webcam conectada

## Instalação (PowerShell)

Na pasta do projeto:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Se a ativação do ambiente virtual estiver bloqueada, execute diretamente:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Executar

```powershell
python main.py
```

Pressione `q` para fechar a janela.

## Comportamento esperado

- A imagem é espelhada por padrão, como em um espelho.
- MediaPipe recebe a imagem espelhada para que a classificação de lateralidade siga a convenção de câmera selfie. Se o espelhamento for desativado, o código inverte a etiqueta de lateralidade para compensar essa convenção.
- Somente a mão classificada como `Right` é desenhada e contabilizada.
- Os 21 landmarks e as conexões da mão são exibidos.
- O painel mostra o estado da detecção e o FPS estimado.

## Configuração

Edite `config/settings.json`:

- `camera.index`: índice da webcam (0 normalmente é a câmera padrão).
- `camera.width` / `camera.height`: resolução solicitada.
- `camera.mirror`: espelhamento da imagem. Mantenha `true` para a convenção de lateralidade usada nesta POC.
- `tracking.target_hand`: `Right` por padrão.
- `tracking.detection_confidence`: confiança mínima para detecção.
- `tracking.tracking_confidence`: confiança mínima para acompanhar a mão.
- `tracking.show_landmark_indices`: mostra os índices de 0 a 20 para depuração.

Se houver mais de uma câmera, tente `camera.index` como `1` ou `2`.

## Limites desta fase

Esta fase valida apenas captura, detecção, lateralidade e visualização. Ainda não reconhece o gesto de empurrar, não envia comandos e não interage com o jogo.

## Observação sobre lateralidade

O MediaPipe Hands clássico interpreta a classificação esquerda/direita assumindo uma entrada espelhada (selfie). Por isso, a aplicação espelha o frame antes da inferência quando `camera.mirror` está ativado. A aplicação também compensa automaticamente a lateralidade quando `mirror` estiver desativado.
