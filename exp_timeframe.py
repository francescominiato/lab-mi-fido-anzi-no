"""
Esperimento C6 — TIMEFRAME NON PROVATI: 4 ore e settimanale (giu 2026).

Critica: "e i timeframe che non hai provato? 4 ore, settimanale?"

Rifacciamo il walk-forward (stesso motore long-only/all-in del daily ufficiale,
con stop varianti) su 4h (240 min) e settimanale (10080 min), aggregati al volo
dal file Kraken da `load_candles_csv` (genera la cache <file>.c<N>.csv).

Per il settimanale: prima con la soglia "anno pieno" (richiede tanti dati per
anno) → mostra che NON bastano; poi con soglia abbassata → riportiamo cosa esce
(su pochissimi dati, da prendere con le molle).

Avvio:  .venv/bin/python -m lab.exp_timeframe
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lab.data import load_candles_csv
from lab.portfolio import buy_and_hold, run_backtest
from lab.sweep import build_configs

TRAIN_YEARS = 3
STOP_VARIANTS = [("no-stop", False, 0.0), ("stop10%", True, 0.10)]
PATH = "data/XBTEUR.csv"


def walkforward(candles, configs, min_candles_per_year):
    years: dict[int, list[int]] = {}
    for i, c in enumerate(candles):
        years.setdefault(datetime.fromtimestamp(c.ts).year, []).append(i)
    full = {y for y, idx in years.items() if len(idx) >= min_candles_per_year}

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
            for slabel, son, spct in STOP_VARIANTS:
                r = run_backtest(tr_c, [pos_full[i] for i in tr_idx],
                                 stop_loss_on=son, stop_loss_pct=spct,
                                 trend_filter_on=False, position_sizing=False)
                if best is None or r.return_pct > best[0]:
                    best = (r.return_pct, label, son, spct, pos_full)
        _, blabel, son, spct, pos_full = best
        r_te = run_backtest(te_c, [pos_full[i] for i in te_idx],
                            stop_loss_on=son, stop_loss_pct=spct,
                            trend_filter_on=False, position_sizing=False)
        r_bh = buy_and_hold(te_c)
        wf_eq *= (1 + r_te.return_pct / 100)
        bh_eq *= (1 + r_bh.return_pct / 100)
        wins += r_te.return_pct > r_bh.return_pct
        tested += 1
        rows.append((ty, blabel, r_te.return_pct, r_bh.return_pct))
    return wins, tested, wf_eq * 10000, bh_eq * 10000, rows


def report(title, candles, configs, threshold):
    wins, tested, wf, bh, rows = walkforward(candles, configs, threshold)
    print(f"--- {title} (soglia 'anno pieno' = {threshold} candele/anno) ---")
    if not rows:
        print("  Nessun anno qualificato: dati insufficienti per il walk-forward.\n")
        return
    for ty, blabel, r_te, r_bh in rows:
        print(f"  {ty}: {blabel:<22} strat {r_te:>8.1f}% | HODL {r_bh:>8.1f}% | {'WIN' if r_te>r_bh else '-'}")
    print(f"  -> batte HODL: {wins}/{tested} | WF composto {wf:,.0f}€ | HODL {bh:,.0f}€\n")


def main():
    # 4 ORE
    print("===== 4 ORE (240 min) =====")
    c4h = load_candles_csv(PATH, 240)
    print(f"{len(c4h):,} candele 4h")
    cfg4 = build_configs(c4h)
    report("4h walk-forward", c4h, cfg4, 2000)  # ~2190 candele/anno = anno pieno

    # SETTIMANALE
    print("===== SETTIMANALE (10080 min) =====")
    cw = load_candles_csv(PATH, 10080)
    print(f"{len(cw):,} candele settimanali (~52/anno)")
    cfgw = build_configs(cw)
    report("settimanale (soglia stretta)", cw, cfgw, 2000)   # nessun anno la passa
    report("settimanale (soglia abbassata)", cw, cfgw, 40)   # ~anno pieno di settimane


if __name__ == "__main__":
    main()
