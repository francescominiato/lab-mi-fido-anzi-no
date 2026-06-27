"""
Esperimento C3 — IL PREZZO KRAKEN E' IL MERCATO? (cross-check fonti, giu 2026).

Critica: "il tuo storico è solo Kraken, non il mercato globale."

Confrontiamo il PREZZO di BTC da due fonti indipendenti:
  - Kraken  : BTC/EUR daily close (data/XBTEUR.csv.c1440.csv)
  - CoinMetrics: BTC price_usd daily (data/onchain_btc.csv) — fonte diversa

Per confrontare i LIVELLI servono stesse unità: converto CoinMetrics USD -> EUR
col cambio EUR/USD daily (data/EURUSD.csv.c1440.csv), disponibile 2020-2025.

In più, sui RENDIMENTI giornalieri (quasi invarianti al cambio, perché un giorno
di EUR/USD si muove pochissimo rispetto a BTC) confronto Kraken-EUR vs
CoinMetrics-USD su TUTTA la storia comune 2013-2025: correlazione attesa ~1.

Avvio:  .venv/bin/python -m lab.exp_pricecheck
"""

import os
import sys
from datetime import datetime, timezone
from statistics import median, correlation

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_ohlc_close(path):
    """ts,o,h,l,c,v -> {YYYY-MM-DD: close}"""
    out = {}
    with open(path) as f:
        for line in f:
            p = line.strip().split(",")
            if len(p) < 5:
                continue
            d = datetime.fromtimestamp(int(p[0]), tz=timezone.utc).strftime("%Y-%m-%d")
            out[d] = float(p[4])
    return out


def load_coinmetrics(path):
    """time,price_usd,... -> {YYYY-MM-DD: price_usd}"""
    out = {}
    with open(path) as f:
        next(f)  # header
        for line in f:
            p = line.strip().split(",")
            if len(p) < 2 or not p[1]:
                continue
            out[p[0]] = float(p[1])
    return out


def pctile(sorted_vals, q):
    i = int(q * (len(sorted_vals) - 1))
    return sorted_vals[i]


def main():
    kraken = load_ohlc_close("data/XBTEUR.csv.c1440.csv")     # BTC/EUR
    eurusd = load_ohlc_close("data/EURUSD.csv.c1440.csv")     # EUR/USD
    cm = load_coinmetrics("data/onchain_btc.csv")             # BTC/USD
    # cambio sano (scarta artefatti di aggregazione ai bordi)
    eurusd = {d: v for d, v in eurusd.items() if 0.9 <= v <= 1.3}

    print(f"Kraken BTC/EUR: {len(kraken)} giorni | CoinMetrics BTC/USD: {len(cm)} giorni "
          f"| EUR/USD: {len(eurusd)} giorni\n")

    # --- (A) LIVELLI, finestra con cambio (2020-2025) -----------------------
    diffs = []
    for d in sorted(set(kraken) & set(cm) & set(eurusd)):
        cm_eur = cm[d] / eurusd[d]            # USD -> EUR
        diffs.append(abs(kraken[d] - cm_eur) / cm_eur * 100)
    diffs.sort()
    print("=== (A) LIVELLI: Kraken BTC/EUR vs (CoinMetrics USD / EURUSD) ===")
    print(f"giorni confrontati: {len(diffs)} (finestra con cambio EUR/USD)")
    print(f"differenza % assoluta — mediana {median(diffs):.3f}% | "
          f"media {sum(diffs)/len(diffs):.3f}% | 90° pct {pctile(diffs,0.90):.3f}% | "
          f"max {diffs[-1]:.3f}%")
    within = sum(1 for x in diffs if x <= 1.0) / len(diffs) * 100
    print(f"giorni entro l'1% di scarto: {within:.1f}%\n")

    # --- (B) RENDIMENTI giornalieri su TUTTA la storia comune ---------------
    common = sorted(set(kraken) & set(cm))
    kr_ret, cm_ret = [], []
    for a, b in zip(common, common[1:]):
        # giorni consecutivi (la cache è giornaliera contigua)
        if kraken[a] > 0 and cm[a] > 0:
            kr_ret.append(kraken[b] / kraken[a] - 1)
            cm_ret.append(cm[b] / cm[a] - 1)
    print("=== (B) RENDIMENTI giornalieri: Kraken-EUR vs CoinMetrics-USD (tutta la storia) ===")
    print(f"giorni: {len(kr_ret)} ({common[0]} -> {common[-1]})")
    print(f"correlazione rendimenti: {correlation(kr_ret, cm_ret):.4f}")


if __name__ == "__main__":
    main()
