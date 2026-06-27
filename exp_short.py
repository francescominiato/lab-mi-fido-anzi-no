"""
Esperimento C5 — LONG-SHORT sul daily (giu 2026).

Critica: "hai testato solo long-only; in un orso lo short avrebbe guadagnato.
Ovvio che non batti il compra&tieni, operi con una mano legata."

Esperimento: abilitare lo SHORT nelle trend-following (EMA crossover, breakout)
sul giornaliero e passarle al walk-forward, confrontandole con le STESSE
strategie long-only — sotto lo STESSO motore (returns-based, all-in), così il
confronto isola l'effetto dello short e non il motore.

- LONG-ONLY: +1 quando il trend è su, 0 (liquido) quando è giù.
- LONG-SHORT: +1 quando è su, -1 (scommetti sul ribasso) quando è giù.

Motore: all-in, costo = fee × turnover (flip long->short = 2 fee). Niente stop
(manopola separata), per isolare l'effetto dello short.

Avvio:  .venv/bin/python -m lab.exp_short
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lab.data import load_candles_csv
from lab.strategies import ema

FEE = 0.0026
TRAIN_YEARS = 3
PATH = "data/XBTEUR.csv"
EMA_PAIRS = [(9, 21), (9, 50), (12, 100), (20, 50), (20, 200), (50, 200)]
BREAKOUTS = [10, 20, 55, 100]


# --- Generatori di posizioni (long-only 0/+1  e  long-short -1/+1) ----------

def pos_ema(candles, fast, slow, short):
    closes = [c.close for c in candles]
    f, s = ema(closes, fast), ema(closes, slow)
    down = -1 if short else 0
    out = []
    for i in range(len(candles)):
        if f[i] is None or s[i] is None:
            out.append(0)
        else:
            out.append(1 if f[i] > s[i] else down)
    return out


def pos_breakout(candles, lookback, short):
    down = -1 if short else 0
    out = [0] * len(candles)
    pos = 0
    for i in range(len(candles)):
        if i >= lookback:
            window = candles[i - lookback:i]
            hi = max(c.high for c in window)
            lo = min(c.low for c in window)
            if candles[i].close > hi:
                pos = 1
            elif candles[i].close < lo:
                pos = down
        out[i] = pos
    return out


def build_configs(candles, short):
    cfgs = []
    for fast, slow in EMA_PAIRS:
        cfgs.append((f"EMA {fast}/{slow}", pos_ema(candles, fast, slow, short)))
    for lb in BREAKOUTS:
        cfgs.append((f"Breakout {lb}", pos_breakout(candles, lb, short)))
    return cfgs


# --- Motore returns-based all-in con short e costo sul turnover --------------

def run_ls(candles, positions, fee=FEE):
    E = 1.0
    prev_p = 0
    n = len(candles)
    for i in range(n):
        p = positions[i]
        E *= (1 - fee * abs(p - prev_p))   # costo per spostarsi alla posizione p
        prev_p = p
        if i + 1 < n:
            r = candles[i + 1].close / candles[i].close - 1
            E *= (1 + p * r)               # rendimento realizzato tenendo p
    E *= (1 - fee * abs(prev_p))           # chiusura finale
    return (E - 1) * 100


def buy_hold(candles, fee=FEE):
    return run_ls(candles, [1] * len(candles), fee)


# --- Walk-forward -----------------------------------------------------------

def walkforward(candles, short, verbose=False):
    years: dict[int, list[int]] = {}
    for i, c in enumerate(candles):
        years.setdefault(datetime.fromtimestamp(c.ts).year, []).append(i)
    full = {y for y, idx in years.items() if len(idx) >= 200}
    configs = build_configs(candles, short)

    wf_eq = 1.0
    bh_eq = 1.0
    wins = 0
    tested = 0
    rows = []
    for ty in sorted(years):
        tr_years = [ty - k for k in range(1, TRAIN_YEARS + 1)]
        if ty not in full or any(t not in full for t in tr_years):
            continue
        tr_idx = sorted(i for t in tr_years for i in years[t])
        te_idx = years[ty]
        tr_c = [candles[i] for i in tr_idx]
        te_c = [candles[i] for i in te_idx]

        best = None
        for label, pos_full in configs:
            r = run_ls(tr_c, [pos_full[i] for i in tr_idx])
            if best is None or r > best[0]:
                best = (r, label, pos_full)
        _, blabel, pos_full = best
        r_te = run_ls(te_c, [pos_full[i] for i in te_idx])
        r_bh = buy_hold(te_c)
        wf_eq *= (1 + r_te / 100)
        bh_eq *= (1 + r_bh / 100)
        wins += r_te > r_bh
        tested += 1
        rows.append((ty, blabel, r_te, r_bh))
    return wins, tested, wf_eq * 10000, bh_eq * 10000, rows


def main():
    candles = load_candles_csv(PATH, 1440)
    print(f"Daily, {len(candles):,} candele. Motore returns-based all-in, fee {FEE*100:.2f}%, no-stop.\n")

    for short, name in [(False, "LONG-ONLY"), (True, "LONG-SHORT")]:
        wins, tested, wf, bh, rows = walkforward(candles, short)
        print(f"=== {name} (trend-following: EMA + breakout) ===")
        print(f"{'anno':>5} | {'scelta sul train':<14} | {'strategia':>10} | {'HODL':>10} | esito")
        for ty, blabel, r_te, r_bh in rows:
            print(f"{ty:>5} | {blabel:<14} | {r_te:>9.1f}% | {r_bh:>9.1f}% | {'WIN' if r_te>r_bh else '-'}")
        print(f"  -> batte HODL: {wins}/{tested} | WF composto {wf:,.0f}€ | HODL {bh:,.0f}€\n")


if __name__ == "__main__":
    main()
