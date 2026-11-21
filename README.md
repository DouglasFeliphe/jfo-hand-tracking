# JFO Hand Tracking — Fase 2

POC de reconhecimento local do gesto de Force Push usando uma única mão direita diante da webcam. Nesta fase, o sistema **não envia comandos ao jogo**.

## Requisitos

- Windows 10/11
- Python 3.12 de 64 bits
- Webcam

## Instalação (PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Executar

```powershell
.\.venv\Scripts\python.exe main.py
```

Pressione `q` para encerrar.

## Gesto reconhecido

1. Mostre a mão direita com a palma aberta.
2. Mantenha a palma estável por aproximadamente 0,35 segundo.
3. Quando o estado mudar para `ARMED`, empurre a mão em direção à webcam.
4. O sistema deverá exibir `FORCE PUSH DETECTED` e registrar o evento no terminal.
5. Para rearmar, aguarde o cooldown e feche a mão por um breve período.

O reconhecimento usa ângulos das articulações para detectar dedos estendidos, separação do polegar, crescimento aparente da palma e variação de profundidade estimada pelo MediaPipe. O aumento aparente da palma é a pista principal; o valor Z é usado como confirmação, pois a estimativa monocular pode oscilar.

## Ajustes

Edite `config/settings.json`:

- `tracking.model_complexity`: padrão `0`, prioriza velocidade.
- `display.processing_width`: largura usada na inferência; padrão `640`.
- `gestures.open_palm_angle`: ângulo mínimo para considerar os quatro dedos estendidos.
- `gestures.thumb_spread_ratio`: separação mínima do polegar.
- `gestures.arm_stability_seconds`: tempo de palma aberta para armar.
- `gestures.scale_trigger_ratio`: aumento mínimo da escala da palma.
- `gestures.scale_strong_ratio`: aumento forte que pode confirmar o gesto mesmo se Z estiver ruidoso.
- `gestures.z_trigger_delta`: variação mínima de Z para corroborar o movimento em direção à câmera.
- `gestures.cooldown_seconds`: intervalo mínimo antes de permitir rearme.

## Testes automatizados

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Limites desta fase

- Apenas a mão direita é considerada.
- Apenas Force Push é reconhecido.
- Não há comunicação com Jedi: Fallen Order nesta fase.
- Os limiares são valores iniciais e deverão ser calibrados com a webcam e iluminação reais.
- Uma webcam monocular não mede profundidade física com precisão; por isso o reconhecimento combina escala aparente, Z estimado e estabilidade temporal.
