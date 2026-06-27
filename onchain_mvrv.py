"""
lab/onchain_mvrv.py — Event study sulla determinante MVRV (termometro di valutazione).

Diverso dal netflow: MVRV non è un flusso, è un LIVELLO di valutazione.
  MVRV = valore di mercato / costo base aggregato (realized value).
    • MVRV < 1            → mediamente gli holder sono in PERDITA (zona di fondo) → ipotesi SU
    • MVRV ≥ soglia alta  → forte sopravvalutazione (zona di euforia/top)        → ipotesi GIÙ/debole

Usa soglie ASSOLUTE perché hanno un significato economico (sotto 1 = sotto il costo
medio di chi ha comprato), non z-score. Orizzonti LUNGHI: è un segnale di CICLO.

⚠ Caveat onestà: le zone estreme di MVRV sono RARE e fatte di giorni CONSECUTIVI (pochi
episodi lunghi). Quindi i "n" sono giorni AUTOCORRELATI, non casi indipendenti: la potenza
statistica è molto minore di quella che il numero suggerisce. Leggere con prudenza.

Uso:
    .venv/bin/python -m lab.onchain_mvrv [soglia_bassa=1.0] [soglia_alta=3.0] [--finestre 3:1]
"""

import csv
import os
import statistics
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(QUI), "data", "onchain_btc.csv")

ORIZZONTI = [30, 90, 180]        # giorni dopo (MVRV è lento: orizzonti di ciclo)
ORIZ_MAX = max(ORIZZONTI)


def carica():
    righe = []
    with open(DATA, newline="") as f:
        for r in csv.DictReader(f):
            p, m = r["price_usd"], r["mvrv"]
            if p == "" or m == "":
                continue
            righe.append({"time": r["time"], "price": float(p), "mvrv": float(m)})
    return righe


def metriche(indici, righe):
    n_tot = len(righe)
    out = {"n": len(indici)}
    for k in ORIZZONTI:
        rets = [righe[i + k]["price"] / righe[i]["price"] - 1
                for i in indici if i + k < n_tot]
        out[f"med{k}"] = statistics.median(rets) if rets else None
    su = tot = 0
    maes, mfes = [], []
    for i in indici:
        if i + ORIZ_MAX >= n_tot:
            continue
        p0 = righe[i]["price"]
        path = [righe[i + j]["price"] / p0 - 1 for j in range(1, ORIZ_MAX + 1)]
        tot += 1
        su += 1 if path[-1] > 0 else 0
        maes.append(min(path))
        mfes.append(max(path))
    out["prob"] = (100 * su / tot) if tot else None
    out["mae"] = statistics.fmean(maes) if maes else None
    out["mfe"] = statistics.fmean(mfes) if mfes else None
    return out


def _pct(x):
    return f"{x * 100:+.1f}%" if x is not None else "     —"


def gruppi(indici, bassa, alta, righe):
    basso = [i for i in indici if righe[i]["mvrv"] <= bassa]
    alto = [i for i in indici if righe[i]["mvrv"] >= alta]
    return basso, alto, indici


def stampa_tabella(basso, alto, base, righe, bassa, alta):
    mb_, ma_, mbase = (metriche(g, righe) for g in (basso, alto, base))
    print(f"\n{'Metrica':<22}{f'MVRV≤{bassa} (fondo)':>18}{f'MVRV≥{alta} (euforia)':>20}{'Baseline':>12}")
    print("-" * 72)
    print(f"{'n. giorni':<22}{mb_['n']:>18}{ma_['n']:>20}{mbase['n']:>12}")
    for k in ORIZZONTI:
        print(f"{'Ret mediano +' + str(k) + 'g':<22}"
              f"{_pct(mb_[f'med{k}']):>18}{_pct(ma_[f'med{k}']):>20}{_pct(mbase[f'med{k}']):>12}")
    for et, ch in [("Prob. su +180g", "prob"), ("MAE medio (180g)", "mae"), ("MFE medio (180g)", "mfe")]:
        def f(m):
            if m[ch] is None:
                return "—"
            return f"{m[ch]:.1f}%" if ch == "prob" else _pct(m[ch])
        print(f"{et:<22}{f(mb_):>18}{f(ma_):>20}{f(mbase):>12}")


def stampa_split(validi, bassa, alta, righe, frazione=0.70):
    taglio = int(len(validi) * frazione)
    print("\n" + "=" * 72)
    print("VERIFICA DI STABILITÀ — SPLIT 70/30")
    print("=" * 72)
    for nome, idx in [("IN-SAMPLE (primo 70%)", validi[:taglio]),
                      ("OUT-OF-SAMPLE (ultimo 30%)", validi[taglio:])]:
        if not idx:
            continue
        basso, alto, base = gruppi(idx, bassa, alta, righe)
        mb_, ma_, mbase = (metriche(g, righe) for g in (basso, alto, base))
        print(f"\n{nome}   ({righe[idx[0]]['time']} → {righe[idx[-1]]['time']})")
        for nm, m in [(f"MVRV≤{bassa}", mb_), (f"MVRV≥{alta}", ma_), ("Baseline", mbase)]:
            if m["n"] == 0:
                print(f"  {nm:<12} n=   0   (nessun giorno in zona)")
                continue
            avv = "  ⚠ pochi/autocorr." if (m["n"] < 30 and nm != "Baseline") else ""
            prob = f"{m['prob']:.1f}%" if m["prob"] is not None else "—"
            print(f"  {nm:<12} n={m['n']:>4}   ret mediano +180g {_pct(m['med180'])}   prob su {prob}{avv}")


def stampa_finestre(validi, bassa, alta, righe, ampiezza=3, passo=1):
    anni = sorted({int(righe[i]["time"][:4]) for i in validi})
    print("\n" + "=" * 72)
    print(f"FINESTRE SCORREVOLI ({ampiezza} anni, passo {passo}) — la zona compare e tiene il segno?")
    print("=" * 72)
    print("Mostra, per finestra: n giorni in zona e ret mediano +180g (vs baseline).\n")
    for start in range(anni[0], anni[-1] - ampiezza + 2, passo):
        end = start + ampiezza
        idx = [i for i in validi if start <= int(righe[i]["time"][:4]) < end]
        if not idx:
            continue
        basso, alto, base = gruppi(idx, bassa, alta, righe)
        mb_, ma_, mbase = (metriche(g, righe) for g in (basso, alto, base))

        def cella(m):
            if m["n"] == 0:
                return "n=  0        —"
            avv = "⚠" if m["n"] < 30 else " "
            return f"n={m['n']:>3}{avv} med {_pct(m['med180'])}"

        print(f"  {start}-{end - 1}  base {_pct(mbase['med180'])}   "
              f"FONDO {cella(mb_)}   EUFORIA {cella(ma_)}")


def main():
    args = sys.argv[1:]
    flag_fin, pos, i = None, [], 0
    while i < len(args):
        if args[i] == "--finestre":
            if i + 1 < len(args) and ":" in args[i + 1]:
                flag_fin = args[i + 1]; i += 2
            else:
                flag_fin = "3:1"; i += 1
        else:
            pos.append(args[i]); i += 1
    bassa = float(pos[0]) if len(pos) > 0 else 1.0
    alta = float(pos[1]) if len(pos) > 1 else 3.0

    righe = carica()
    validi = [i for i in range(len(righe)) if i + ORIZ_MAX < len(righe)]

    print("=" * 72)
    print("EVENT STUDY ON-CHAIN — MVRV (termometro di valutazione, non grafico)")
    print("=" * 72)
    print(f"Soglie: fondo MVRV≤{bassa}  ·  euforia MVRV≥{alta}  ·  orizzonti +30/+90/+180g")
    print(f"Periodo: {righe[validi[0]]['time']} → {righe[validi[-1]]['time']}  ({len(validi)} giorni)")
    print("Ipotesi: FONDO (MVRV basso) → su ;  EUFORIA (MVRV alto) → giù/debole")
    print("⚠ zone estreme = giorni consecutivi autocorrelati → potenza statistica bassa")

    basso, alto, base = gruppi(validi, bassa, alta, righe)
    print(f"\nGiorni in zona: fondo (≤{bassa}) = {len(basso)}  |  euforia (≥{alta}) = {len(alto)}")

    stampa_tabella(basso, alto, base, righe, bassa, alta)
    stampa_split(validi, bassa, alta, righe)
    if flag_fin:
        amp, passo = (int(x) for x in flag_fin.split(":"))
        stampa_finestre(validi, bassa, alta, righe, amp, passo)
    print("\n" + "=" * 72)


if __name__ == "__main__":
    main()
