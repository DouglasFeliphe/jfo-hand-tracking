# JFO Hand Tracking — Phase 4

Reconhece gestos das duas mãos e os transmite por TCP (`127.0.0.1:8765`) a um adaptador, que pressiona a tecla da habilidade no Jedi: Fallen Order. Enquanto o gesto é mantido, a tecla **continua pressionada**; ao terminá-lo, ela é solta.

| Habilidade              | Mão      | Gesto                                                                                                                            | Tecla |
| ----------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------- | ----- |
| Empurrão (`FORCE_PUSH`) | Direita  | Palma aberta parada e depois um avanço da mão para a câmera. Mantenha a mão estendida para segurar.                              | `2`   |
| Lentidão (`FORCE_SLOW`) | Esquerda | Varrida horizontal para a sua direita com a palma aberta ("abrir uma cortina"). A tecla fica pressionada só durante o movimento. | `1`   |

Cada mão tem o seu gesto, então os dois podem acontecer ao mesmo tempo.

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

### `gestures` (empurrão)

| Campo                                   | Descrição                                                                                                                                                                                                                                             |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `open_palm_angle`, `thumb_spread_ratio` | O que conta como palma aberta (dedos estendidos e polegar afastado).                                                                                                                                                                                  |
| `arm_stability_seconds`                 | Tempo de palma aberta parada antes de armar. Padrão 0,20.                                                                                                                                                                                             |
| `smoothing_samples`                     | Mediana sobre N quadros (mais = mais estável, mais atraso). Padrão 3.                                                                                                                                                                                 |
| `push_window_seconds`                   | O empurrão é o crescimento da palma **nesta janela** (padrão 0,30 s). Empurrões mais lentos que isso não disparam; é o que impede que inclinar o corpo devagar dispare. Aumente para aceitar empurrões mais lentos, ao custo de mais falsos disparos. |
| `scale_trigger_ratio`                   | Limiar de crescimento **de reserva**, usado nos primeiros ~0,7 s, até haver amostras para estimar o ruído (ou sempre, com `adaptive_threshold: false`).                                                                                               |
| `scale_strong_ratio`                    | Crescimento forte o bastante para disparar sem apoio do `z`. Mantém a mesma diferença para o limiar em vigor.                                                                                                                                         |
| `z_trigger_delta`                       | Queda mínima do `z` do MediaPipe (apoio) na janela.                                                                                                                                                                                                   |
| `anisotropy_tolerance`                  | O desbalanço entre comprimento e largura da palma precisa ser no máximo esta vez o crescimento. Empurrar cresce os dois igualmente; **girar a mão** muda quase só a largura e é rejeitado. `0` exige crescimento perfeitamente uniforme.              |
| `adaptive_threshold`                    | Liga o limiar adaptativo (abaixo).                                                                                                                                                                                                                    |
| `noise_k`                               | Quantos desvios de ruído acima de 1,0 fica o limiar. Padrão 4.                                                                                                                                                                                        |
| `min_scale_trigger`                     | **Piso** do limiar adaptativo (padrão 1,06). Menor = disparo mais rápido e detecta empurrões fracos, mas mais sensível a pequenas oscilações de profundidade.                                                                                         |
| `max_scale_trigger`                     | **Teto** do limiar adaptativo (padrão 1,12). Com tracking muito ruidoso, o empurrão precisa ser mais forte que isso.                                                                                                                                  |
| `cooldown_seconds`                      | Espera mínima depois do disparo antes de poder rearmar. Padrão 0,50.                                                                                                                                                                                  |
| `rearm_on_retract`                      | `true`: depois de recuar a mão aberta, já rearma sem fechar o punho.                                                                                                                                                                                  |
| `hold_enabled`                          | `false` desativa o segurar: a tecla é solta no quadro seguinte (toque).                                                                                                                                                                               |
| `hold_release_ratio`                    | Escala da palma (relativa à escala **de antes do empurrão**) abaixo da qual a mão é considerada recuada. Padrão 1,04.                                                                                                                                 |
| `hold_release_seconds`                  | Tempo que o fim da pose precisa durar para soltar (evita soltar por um quadro ruim).                                                                                                                                                                  |
| `hold_lost_grace_seconds`               | Tolerância a perda de rastreamento antes de soltar.                                                                                                                                                                                                   |

### `slow_gesture` (lentidão, varrida)

| Campo                       | Descrição                                                                                                                  |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `enabled`                   | `false` desativa o gesto de lentidão. Com ele ativo, o programa usa `max_hands >= 2`.                                      |
| `hand`                      | Mão que faz a varrida (`Left` ou `Right`).                                                                                 |
| `direction`                 | `right` ou `left`, relativo a você (com a imagem espelhada, `right` é para a direita da janela).                           |
| `finger_extended_angle`     | Ângulo mínimo para os 4 dedos contarem como estendidos (palma aberta).                                                     |
| `start_speed`               | Velocidade mínima para começar, em larguras de palma por segundo (independe da distância da câmera). Padrão 3,0.           |
| `min_travel`                | Deslocamento mínimo (em larguras de palma) para confirmar a varrida. Padrão 0,6. Menor = dispara mais cedo, mais sensível. |
| `stop_speed`                | Abaixo desta velocidade a mão é considerada parada (histerese; precisa ser menor que `start_speed`).                       |
| `stop_seconds`              | Tempo parada antes de soltar a tecla.                                                                                      |
| `horizontal_dominance`      | O deslocamento horizontal precisa ser pelo menos esta vez o vertical. Evita disparar com movimentos diagonais.             |
| `velocity_window_seconds`   | Janela usada para medir a velocidade.                                                                                      |
| `candidate_timeout_seconds` | Tempo máximo para completar `min_travel` depois que a velocidade passa de `start_speed`.                                   |
| `min_tracking_seconds`      | A mão precisa estar visível por este tempo antes de poder disparar (evita disparar ao entrar na imagem já em movimento).   |
| `max_hold_seconds`          | Teto de segurança: solta a tecla mesmo se a mão continuar se movendo.                                                      |
| `cooldown_seconds`          | Espera mínima depois de soltar; a mão também precisa estar quase parada para rearmar.                                      |
| `hold_lost_grace_seconds`   | Tolerância a perda de rastreamento antes de soltar.                                                                        |

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

## Empurrão: como o disparo funciona (Fase 5)

O empurrão é detectado como **crescimento recente** da palma, não como "ficou maior que quando armou":

1. **Janela deslizante.** A escala atual é comparada com a de `push_window_seconds` atrás. Um movimento lento (inclinar-se para a câmera) não cresce o bastante dentro da janela; um empurrão rápido, sim.
2. **Isotropia.** Empurrar faz o comprimento e a largura da palma crescerem juntos. Girar a mão muda quase só um deles e é descartado, mesmo com o `z` ruidoso ajudando.
3. **Tamanho da palma robusto.** A escala usa 10 distâncias da palma (pulso até os nós dos dedos e entre eles), então o tremor de cada landmark se compensa.
4. **Limiar adaptativo.** O programa estima o ruído de rastreamento da escala com um estimador robusto (mediana dos desvios, que ignora o próprio empurrão) e põe o limiar `noise_k` desvios acima, entre `min_scale_trigger` e `max_scale_trigger`. Tracking limpo: limiar baixo, disparo mais rápido. Tracking ruidoso: limiar alto, mais seguro.
5. **Segurar com a referência certa.** A escala de "antes do empurrão" vira a referência para soltar. Antes, ela era a de quando você armou, então quem se inclinou devagar antes de empurrar ficava segurando a tecla.
6. **Rearme sem fechar o punho.** Recuar a mão aberta e parar já rearma (`rearm_on_retract`).

O painel mostra `PUSH TRIGGER` (limiar em vigor), `NOISE` (ruído estimado) e `ISO` (isotropia), úteis para ajustar.

### Resultados medidos em simulação

Mão sintética a 30 FPS com tremor de 1,5% do tamanho da palma por landmark (`tools/evaluate_push.py` reproduz os números com os seus valores). Antigo = critério da Fase 4 com os valores recomendados na época.

| Situação                                       | Antigo             | Novo     |
| ---------------------------------------------- | ------------------ | -------- |
| Inclinar-se devagar (+20% em 2 s) dispara?     | 100% das execuções | 0%       |
| Girar a mão (largura +30% em 0,4 s) dispara?   | 48%                | 0%       |
| Girar a mão com `z` ruidoso a favor            | 100%               | 18%      |
| Mão aberta parada, 60 s                        | 0%                 | 0%       |
| Oscilar em profundidade ±3% a 1,5 Hz           | 0%                 | **100%** |
| Atraso, empurrão de +12% em 0,25 s             | 228 ms             | 190 ms   |
| Atraso, empurrão de +8% em 0,15 s              | 227 ms             | 169 ms   |
| Atraso, empurrão de +30% em 0,25 s             | 122 ms             | 111 ms   |
| Detecção, empurrão fraco (+8% em 0,5 s)        | 100%               | 28%      |
| Tempo entre dois empurrões, sem fechar o punho | não rearma         | 1,20 s   |
| Tempo entre dois empurrões, fechando o punho   | 1,87 s             | 1,60 s   |

**O que piorou, e por quê:**

- **Oscilar a mão para frente e para trás** (±3% a 1,5 Hz, ou seja, ±1,5 cm a 50 cm da câmera) agora dispara. Isso se parece com empurrões pequenos e repetidos. O piso `min_scale_trigger` controla isso: com 1,07 dispara em 93% das execuções de ±3% e em 3% das de ±2%; com 1,08 cai para 27% e 0%.
- **Empurrões lentos e fracos** deixam de disparar porque não cabem na janela. É o preço de não disparar ao se inclinar para a câmera. Aumente `push_window_seconds` (0,30 → 0,40) se você empurra devagar.
- Com tracking **muito** ruidoso (tremor de 3–4% da palma), o limiar sobe até o teto e empurrões de +12% passam a ser detectados só em ~60–70% das tentativas. É o comportamento seguro; melhore a luz ou a câmera, ou aumente `max_scale_trigger` se preferir sensibilidade.

### Ajuste rápido

| Sintoma                           | Ajuste                                                 |
| --------------------------------- | ------------------------------------------------------ |
| Dispara sem querer ao mexer a mão | `min_scale_trigger` 1,06 → 1,07 ou 1,08                |
| Precisa empurrar forte demais     | `min_scale_trigger` 1,06 → 1,05; ou `noise_k` 4 → 3    |
| Empurrões lentos não disparam     | `push_window_seconds` 0,30 → 0,40                      |
| Dispara ao girar a mão            | `anisotropy_tolerance` 1,0 → 0,7                       |
| Atraso geral                      | veja a câmera abaixo; depois `smoothing_samples` 3 → 2 |

### Latência da câmera

Parte do atraso vem da captura, não do reconhecimento. Olhe o `FPS` no painel: abaixo de ~25, a imagem é o gargalo. Em `camera`, você pode adicionar `"fourcc": "MJPG"` (muitas webcams USB só chegam a 30 FPS em 720p com esse formato) ou reduzir `width`/`height` para 640×480. O buffer de captura já usa 1 quadro (`buffer_size`; alguns drivers ignoram). Não consegui medir o efeito sem uma webcam, então valide o FPS no seu equipamento.

## Lentidão (varrida com a mão esquerda)

A lentidão usa a tecla `1`. Segundo a wiki do jogo, um toque ativa a lentidão e segurar dá um efeito maior, então o binding usa `allow_hold: true`.

- **Disparo:** palma aberta e uma varrida rápida para a sua direita (velocidade ≥ `start_speed` e deslocamento ≥ `min_travel`) → START.
- **Manter:** a tecla fica pressionada enquanto a mão continuar se movendo com a palma aberta.
- **Soltar:** a mão parar, fechar, voltar para a esquerda ou sair da imagem → STOP.
- Um gesto muito curto ainda vira um toque, porque a tecla fica pressionada pelo menos `hold_ms`.
- A velocidade é medida em larguras de palma por segundo, então funciona mais perto ou mais longe da câmera.

Valores medidos em simulação a 30 FPS: o disparo leva de 100 a 300 ms conforme a velocidade da varrida (≈ 200 ms a 5 palmas/s) e a tecla é solta cerca de 230 ms depois que a mão para. Tremor da mão parada não dispara. Acenar de um lado para o outro dispara a cada ida, porque cada ida é uma varrida; a volta para a esquerda é ignorada.

Ajustes comuns: se não disparar, diminua `start_speed` (3,0 → 2,5) ou `min_travel`. Se disparar sem querer, aumente-os. Se a tecla soltar no meio do movimento, diminua `stop_speed` ou aumente `stop_seconds`.

## Adicionando outras habilidades (puxão...)

1. **Binding:** em `game.bindings`, por exemplo `"FORCE_PULL": { "keys": ["3"], "hold_ms": 80, "allow_hold": false }`. O adaptador aceita a habilidade automaticamente. O puxão é um toque, então `allow_hold: false`.
2. **Gesto:** crie um reconhecedor com o mesmo contrato (`update`, `triggered`, `hold_released`, `holding`), como `GestureRecognizer` e `SweepRecognizer`.
3. **Ligação:** em `main.py`, crie a constante da habilidade e chame `dispatch(sender, ABILITY, "RIGHT" ou "LEFT", result)` com o resultado do reconhecedor. O envio já aceita várias habilidades ao mesmo tempo, cada uma com a sua mão.

Duas habilidades não podem compartilhar a mesma tecla.

## Roteiro de validação

1. `mode: dry_run`: ao empurrar, o painel mostra `ADAPTER: DRY_RUN`; ao fechar a mão, `ADAPTER: RELEASED`.
2. `mode: keyboard` e `window_title_contains: "Bloco de Notas"`: empurre e mantenha a mão aberta e estendida. O Bloco de Notas deve repetir `2` (repetição de tecla do Windows enquanto segura). Feche a mão e a repetição para.
3. Durante o segurar, clique em outra janela: a tecla deve ser solta (perda de foco).
4. Durante o segurar, feche a janela da webcam à força: em até 0,5 s a tecla deve ser solta (watchdog).
5. Lentidão: no modo `dry_run`, com a mão esquerda, faça a varrida para a direita. O painel mostra `SLOW: HOLDING` e `ADAPTER: DRY_RUN (SLOW)`; ao parar a mão, `RELEASED (SLOW)`. No Bloco de Notas, a tecla `1` repete enquanto você move a mão e para quando ela para.
6. Confirme a independência das mãos: empurrar com a direita e varrer com a esquerda ao mesmo tempo.
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

Para avaliar o empurrão com os seus valores do `settings.json`, sem webcam: `.\.venv\Scripts\python.exe tools\evaluate_push.py` (use `--jitter 3` para simular tracking mais ruidoso).

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
├── hand_tracking/         # câmera, detector (duas mãos), gestures (empurrão), sweep (lentidão), landmarks
├── tests/
├── tools/
│   └── evaluate_push.py   # simula o empurrão sem webcam (falsos disparos, atraso)
├── config/settings.json
├── main.py
└── requirements.txt
```

## Limitações conhecidas

- A injeção é por teclado (`SendInput` com scancodes). Não há integração com UE4SS.
- Não há retorno do jogo: o adaptador não sabe se a habilidade realmente foi executada.
- O empurrão se baseia no crescimento 2D da palma (com o `z` do MediaPipe como apoio). A rejeição de rotação e de inclinação lenta foi medida só em simulação; valide com a sua mão e câmera.
- O MediaPipe às vezes rotula as duas mãos igual quando elas se aproximam ou se cruzam (a varrida atravessa o corpo); nesse caso só a detecção mais confiável é usada e o gesto pode falhar naquele instante.
- Rastrear duas mãos usa um pouco mais de CPU; se o FPS cair, desative a lentidão (`slow_gesture.enabled: false`) ou reduza `processing_width`.
- Durante o segurar, se o reconhecimento de "palma aberta" falhar por mais de `hold_release_seconds` (dedos dobrando no movimento), a tecla é solta.
