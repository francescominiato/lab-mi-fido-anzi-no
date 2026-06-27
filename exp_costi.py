"""
Esperimento C2 — SENSIBILITA' AI COSTI (giu 2026).

Domanda: la conclusione "il pigro batte l'attivo" dipende dall'aver usato la
tariffa peggiore di Kraken (0,26% taker)? Rifacciamo i conti con commissioni
piu' basse: 0,26% (taker) -> 0,16% (maker) -> 0,10% -> 0,04%.

- DAILY: walk-forward (train 3 anni -> test 1 anno) per ogni livello di fee.
  Riporta in quanti anni la strategia batte il "compra&tieni" e il capitale composto.
- 15MIN: backtest su 12 anni di tutte le strategie attive, per ogni fee.
  Riporta il rendimento di ognuna vs buy&hold.

Le posizioni si calcolano UNA volta (non dipendono dalla fee); varia solo il costo.

Avvio:  .venv/bin/python -m lab.exp_costi
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lab.data import load_candles_csv
from lab.portfolio import buy_and_hold, run_backtest
from lab.strategies import STRATEGIES
from lab.sweep import build_configs

FEES = [0.0026, 0.0016, 0.0010, 0.0004]
TRAIN_YEARS = 3
STOP_VARIANTS = [("no-stop", False, 0.0), ("stop10%", True, 0.10)]
PATH = "data/XBTEUR.csv"


def walkforward_daily(candles, configs, fee):
    years: dict[int, list[int]] = {}
    for i, c in enumerate(candles):
        years.setdefault(datetime.fromtimestamp(c.ts).year, []).append(i)
    full = {y for y, idx in years.items() if len(idx) >= 200}

    wf_equity = 1.0
    bh_equity = 1.0
    wins = 0
    tested = 0
    for test_year in sorted(years):
        train_years = [test_year - k for k in range(1, TRAIN_YEARS + 1)]
        if test_year not in full or any(ty not in full for ty in train_years):
            continue
        train_idx = sorted(i for ty in train_years for i in years[ty])
        test_idx = years[test_year]
        train_candles = [candles[i] for i in train_idx]
        test_candles = [candles[i] for i in test_idx]

        best = None
        for label, pos_full in configs:
            pos_train = [pos_full[i] for i in train_idx]
            for slabel, son, spct in STOP_VARIANTS:
                r = run_backtest(train_candles, pos_train, fee_rate=fee,
                                 stop_loss_on=son, stop_loss_pct=spct,
                                 trend_filter_on=False, position_sizing=False)
                if best is None or r.return_pct > best[0]:
                    best = (r.return_pct, son, spct, pos_full)
        _, son, spct, pos_full = best
        pos_test = [pos_full[i] for i in test_idx]
        r_test = run_backtest(test_candles, pos_test, fee_rate=fee,
                              stop_loss_on=son, stop_loss_pct=spct,
                              trend_filter_on=False, position_sizing=False)
        r_bh = buy_and_hold(test_candles, fee_rate=fee)
        wf_equity *= (1 + r_test.return_pct / 100)
        bh_equity *= (1 + r_bh.return_pct / 100)
        wins += r_test.return_pct > r_bh.return_pct
        tested += 1
    return wins, tested, wf_equity * 10000, bh_equity * 10000


def main():
    print("=== DAILY — walk-forward (train 3a -> test 1a), all-in ===")
    candles_d = load_candles_csv(PATH, 1440)
    configs = build_configs(candles_d)
    print(f"{'fee':>7} | {'batte HODL':>10} | {'WF composto':>14} | {'HODL composto':>14}")
    for fee in FEES:
        wins, tested, wf, bh = walkforward_daily(candles_d, configs, fee)
        print(f"{fee*100:>6.2f}% | {wins:>4}/{tested:<5} | {wf:>13,.0f}€ | {bh:>13,.0f}€")

    print("\n=== 15MIN — backtest 12 anni, tutte le strategie attive ===")
    candles_m = load_candles_csv(PATH, 15)
    print(f"{len(candles_m):,} candele 15min")
    # posizioni per strategia: calcolate una volta sola
    strat_pos = [(s.name, s.func(candles_m)[0]) for s in STRATEGIES]
    header = f"{'fee':>7} | " + " | ".join(f"{name[:14]:>14}" for name, _ in strat_pos) + f" | {'HODL':>12}"
    print(header)
    for fee in FEES:
        bh = buy_and_hold(candles_m, fee_rate=fee)
        cells = []
        for _, pos in strat_pos:
            r = run_backtest(candles_m, pos, fee_rate=fee,
                             stop_loss_on=False, trend_filter_on=False,
                             position_sizing=False)
            cells.append(f"{r.return_pct:>13.1f}%")
        row = f"{fee*100:>6.2f}% | " + " | ".join(cells) + f" | {bh.return_pct:>10,.0f}%"
        print(row)


if __name__ == "__main__":
    main()
