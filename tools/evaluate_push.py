"""Avalia o gesto de empurrão com mãos sintéticas, sem webcam.

Uso:  python tools/evaluate_push.py [--jitter 1.5] [--trials 20]

Lê a seção "gestures" de config/settings.json e mede, a 30 FPS:
  - falsos disparos em movimentos que NÃO são um empurrão;
  - atraso até o disparo de empurrões reais (e quantos são detectados);
  - o menor tempo entre dois empurrões seguidos.

--jitter é o tremor de rastreamento por landmark, em % do tamanho da palma (0 = mão sintética perfeita).
Os números dependem do modelo de mão e de ruído usados aqui; servem para comparar ajustes entre si,
não para prever o desempenho exato com a sua câmera.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from hand_tracking.gestures import GestureRecognizer  # noqa: E402
from test_gestures import make_hand as _frontal_hand  # noqa: E402

DT = 1 / 30
CENTER = (0.5, 0.55)
PALM_SIZE = 0.286  # tamanho da palma de make_hand(), usado para escalar o tremor


def hand(scale=1.0, yaw=1.0, z=0.0, closed=False, dx=0.0):
    base = _frontal_hand(1.0, 0.0)
    points = []
    for point in base.landmarks.landmark:
        points.append(SimpleNamespace(
            x=CENTER[0] + (point.x - CENTER[0]) * scale * yaw + dx,
            y=CENTER[1] + (point.y - CENTER[1]) * scale,
            z=z,
        ))
    if closed:
        for mcp in (5, 9, 13, 17):
            points[mcp + 3].x, points[mcp + 3].y = points[mcp].x, points[mcp].y
    return SimpleNamespace(landmarks=SimpleNamespace(landmark=points))


def steady(frames, **kwargs):
    return [dict(kwargs) for _ in range(frames)]


def ramp(seconds, scale_to=1.0, scale_from=1.0, yaw_to=1.0, z_per_scale=0.15, **kwargs):
    frames = max(1, round(seconds / DT))
    out = []
    for step in range(1, frames + 1):
        progress = step / frames
        scale = scale_from + (scale_to - scale_from) * progress
        out.append(dict(scale=scale, yaw=1.0 + (yaw_to - 1.0) * progress, z=-z_per_scale * (scale - 1.0), **kwargs))
    return out


def run(config, frames, jitter, seed):
    recognizer = GestureRecognizer(**config)
    rng = random.Random(seed)
    triggers, releases = [], []
    now = 1.0
    for index, frame in enumerate(frames):
        observed = hand(**frame)
        if jitter > 0:
            for point in observed.landmarks.landmark:
                point.x += rng.gauss(0, jitter * PALM_SIZE)
                point.y += rng.gauss(0, jitter * PALM_SIZE)
                point.z += rng.gauss(0, jitter * 0.4)
        result = recognizer.update(observed, now=now)
        if result.triggered:
            triggers.append(index)
        if result.hold_released:
            releases.append(index)
        now += DT
    return triggers, releases


def main() -> int:
    parser = argparse.ArgumentParser(description="Avalia o gesto de empurrão com mãos sintéticas.")
    parser.add_argument("--jitter", type=float, default=1.5, help="tremor por landmark, em %% da palma (padrão 1.5)")
    parser.add_argument("--trials", type=int, default=20, help="execuções por cenário (padrão 20)")
    args = parser.parse_args()

    settings = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
    config = settings["gestures"]
    jitter = args.jitter / 100.0
    arm = steady(30)

    print(f"Configuração: {json.dumps(config)}")
    print(f"Tremor simulado: {args.jitter:.1f}% da palma por coordenada | {args.trials} execuções por cenário\n")

    def hit_rate(frames):
        hits = sum(bool(run(config, frames, jitter, 9000 + seed)[0]) for seed in range(args.trials))
        return 100.0 * hits / args.trials

    print("FALSOS DISPAROS (% de execuções com ao menos 1 disparo; ideal 0%)")
    cases = {
        "palma aberta parada, 30 s": arm + steady(int(30 / DT)),
        "inclinar-se devagar (+20% em 2 s)": arm + ramp(2.0, 1.20) + steady(30, scale=1.2, z=-0.03),
        "inclinar-se devagar (+30% em 3 s)": arm + ramp(3.0, 1.30) + steady(30, scale=1.3, z=-0.045),
        "girar a mão (largura +30% em 0,4 s)": arm + ramp(0.4, yaw_to=1.30, z_per_scale=0.0) + steady(30, yaw=1.3),
        "girar a mão (largura +20% em 0,25 s)": arm + ramp(0.25, yaw_to=1.20, z_per_scale=0.0) + steady(30, yaw=1.2),
        "mover a mão rápido de lado": arm + [dict(dx=0.02 * i) for i in range(1, 20)] + steady(15, dx=0.4),
        "oscilar em profundidade ±2% a 1,5 Hz, 10 s": arm + [dict(scale=1 + 0.02 * math.sin(2 * math.pi * 1.5 * i * DT)) for i in range(int(10 / DT))],
        "oscilar em profundidade ±3% a 1,5 Hz, 10 s": arm + [dict(scale=1 + 0.03 * math.sin(2 * math.pi * 1.5 * i * DT)) for i in range(int(10 / DT))],
    }
    for name, frames in cases.items():
        print(f"  {name:46s} {hit_rate(frames):5.0f}%")

    print("\nEMPURRÕES REAIS: atraso médio até o disparo (% detectado)")
    durations = (0.15, 0.25, 0.35, 0.50)
    print("  crescimento | " + " | ".join(f"T={t:.2f} s     " for t in durations))
    for growth in (0.08, 0.12, 0.20, 0.30):
        cells = []
        for duration in durations:
            frames = arm + ramp(duration, 1 + growth) + steady(15, scale=1 + growth, z=-0.15 * growth)
            latencies = []
            for seed in range(args.trials):
                triggers, _ = run(config, frames, jitter, 500 + seed)
                if triggers and triggers[0] >= len(arm):
                    latencies.append((triggers[0] - len(arm) + 1) * DT * 1000)
            ok = 100.0 * len(latencies) / args.trials
            cells.append(f"{statistics.mean(latencies):4.0f} ms ({ok:3.0f}%)" if latencies else "    falha      ")
        print(f"     +{int(growth * 100):2d}%     | " + " | ".join(cells))

    print("\nEMPURRÃO SEGUINTE: menor tempo entre o 1º e o 2º disparo (empurrar, recuar, empurrar)")
    push = ramp(0.25, 1.15)
    hold = steady(9, scale=1.15, z=-0.0225)
    back = ramp(0.25, 1.0, scale_from=1.15)
    for label, fist_seconds in (("sem fechar o punho", 0.0), ("fechando o punho por 0,6 s", 0.6)):
        fist = steady(round(fist_seconds / DT), closed=True) if fist_seconds else []
        best = None
        for pause in range(0, 91, 2):
            triggers, _ = run(config, arm + push + hold + back + fist + steady(pause) + push + hold, jitter, 77)
            if len(triggers) >= 2:
                gap = (triggers[1] - triggers[0]) * DT
                best = gap if best is None else min(best, gap)
        print(f"  {label:30s} " + (f"{best:.2f} s" if best is not None else "não rearma"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
