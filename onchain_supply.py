"""
lab/onchain_supply.py — Event study sulla SUPPLY NON-EXCHANGE (proxy "illiquid supply").

Determinante: frazione di BTC NON detenuti sugli exchange = (SplyCur − SplyExNtv) / SplyCur.
Idea: più monete escono dagli exchange verso la custodia fredda = meno offerta pronta a
vendere = scarsità. È un segnale di STOCK (lento), diverso dal netflow (flusso giornaliero),
e — come il netflow — NON è contaminato dal prezzo (è un conteggio di monete).

"Estremo" = z-score della frazione su finestra mobile di 90 giorni (toglie il trend secolare
di self-custody, rende confrontabili epoche diverse). z guarda solo i 90 gg PRECEDENTI.
  • ACCUMULO    (z ≥ +soglia): la quota fuori-exchange sale più del solito → ipotesi SU.
  • DISTRIBUZIONE (z ≤ −soglia): monete tornano sugli exchange → ipotesi GIÙ.

Orizzonti lunghi (è uno stock): +30/+60/+90 giorni. Storia: dal 2011 (SplyExNtv).

Uso:
    .venv/bin/python -m lab.onchain_supply [finestra_z=90] [soglia_z=2] [--finestre 3:1]
"""

import csv
import os
import statistics
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(QUI), "data", "onchain_btc.csv")

ORIZZONTI = [30, 60, 90]
ORIZ_MAX = max(ORIZZONTI)


def carica():
    righe = []
    with open(DATA, newline="") as f:
        for r in csv.DictReader(f):
            p, sn, sc = r["price_usd"], r["sply_nonex"], r["supply"]
            if "" in (p, sn, sc) or float(sc) == 0:
                continue
            righe.append({"time": r["time"], "price": float(p),
                          "frac": float(sn) / float(sc)})
    return righe


def calcola_z(righe, fin):
    for i, r in enumerate(righe):
        if i < fin:
            r["z"] = None
            continue
        prev = [righe[j]["frac"] for j in range(i - fin, i)]
        sd = statistics.pstdev(prev)
        r["z"] = (r["frac"] - statistics.fmean(prev)) / sd if sd > 0 else None


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


def gruppi(indici, soglia, righe):
    acc = [i for i in indici if righe[i]["z"] >= soglia]
    dist = [i for i in indici if righe[i]["z"] <= -soglia]
    return acc, dist, indici


def stampa_tabella(acc, dist, base, righe):
    ma, md, mb = (metriche(g, righe) for g in (acc, dist, base))
    print(f"\n{'Metrica':<22}{'Accumulo z≥+s':>16}{'Distribuz. z≤−s':>17}{'Baseline':>12}")
    print("-" * 68)
    print(f"{'n. giorni':<22}{ma['n']:>16}{md['n']:>17}{mb['n']:>12}")
    for k in ORIZZONTI:
        print(f"{'Ret mediano +' + str(k) + 'g':<22}"
              f"{_pct(ma[f'med{k}']):>16}{_pct(md[f'med{k}']):>17}{_pct(mb[f'med{k}']):>12}")
    pr = lambda m: f"{m['prob']:.1f}%" if m['prob'] is not None else "—"
    print(f"{'Prob. su +90g':<22}{pr(ma):>16}{pr(md):>17}{pr(mb):>12}")
    print(f"{'MAE medio (90g)':<22}{_pct(ma['mae']):>16}{_pct(md['mae']):>17}{_pct(mb['mae']):>12}")
    print(f"{'MFE medio (90g)':<22}{_pct(ma['mfe']):>16}{_pct(md['mfe']):>17}{_pct(mb['mfe']):>12}")


def stampa_split(validi, soglia, righe, frazione=0.70):
    taglio = int(len(validi) * frazione)
    print("\n" + "=" * 68)
    print("VERIFICA DI STABILITÀ — SPLIT 70/30")
    print("=" * 68)
    for nome, idx in [("IN-SAMPLE (primo 70%)", validi[:taglio]),
                      ("OUT-OF-SAMPLE (ultimo 30%)", validi[taglio:])]:
        if not idx:
            continue
        acc, dist, base = gruppi(idx, soglia, righe)
        ma, md, mb = (metriche(g, righe) for g in (acc, dist, base))
        print(f"\n{nome}   ({righe[idx[0]]['time']} → {righe[idx[-1]]['time']})")
        for nm, m in [("Accumulo z≥+s", ma), ("Distribuz. z≤−s", md), ("Baseline", mb)]:
            avv = "  ⚠ pochi" if (m["n"] < 30 and nm != "Baseline") else ""
            prob = f"{m['prob']:.1f}%" if m["prob"] is not None else "—"
            print(f"  {nm:<17} n={m['n']:>4}   ret mediano +90g {_pct(m['med90'])}   prob su {prob}{avv}")


def stampa_finestre(validi, soglia, righe, ampiezza=3, passo=1):
    anni = sorted({int(righe[i]["time"][:4]) for i in validi})
    print("\n" + "=" * 68)
    print(f"FINESTRE SCORREVOLI ({ampiezza} anni, passo {passo}) — regge in OGNI epoca?")
    print("=" * 68)
    print("Δ = scarto prob. 'prezzo su +90g' vs baseline.")
    print("Ipotesi: ACCUMULO Δ positivo · DISTRIBUZIONE Δ negativo\n")

    def cella(m, bp):
        if m["prob"] is None:
            return "n=  0   —"
        avv = " ⚠" if m["n"] < 30 else ""
        return f"n={m['n']:>3} prob {m['prob']:>5.1f}% Δ{m['prob'] - bp:+5.1f}{avv}"

    for start in range(anni[0], anni[-1] - ampiezza + 2, passo):
        end = start + ampiezza
        idx = [i for i in validi if start <= int(righe[i]["time"][:4]) < end]
        if not idx:
            continue
        acc, dist, base = gruppi(idx, soglia, righe)
        ma, md, mb = (metriche(g, righe) for g in (acc, dist, base))
        if mb["prob"] is None:
            continue
        print(f"  {start}-{end - 1}  base {mb['prob']:>5.1f}%   "
              f"ACC {cella(ma, mb['prob'])}   DIS {cella(md, mb['prob'])}")


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
    fin = int(pos[0]) if len(pos) > 0 else 90
    soglia = float(pos[1]) if len(pos) > 1 else 2.0

    righe = carica()
    calcola_z(righe, fin)
    validi = [i for i, r in enumerate(righe)
              if r["z"] is not None and i + ORIZ_MAX < len(righe)]

    print("=" * 68)
    print("EVENT STUDY ON-CHAIN — SUPPLY NON-EXCHANGE (proxy illiquid supply)")
    print("=" * 68)
    print(f"Frazione fuori-exchange | z-score su {fin} giorni | soglia ±{soglia}")
    print(f"Periodo: {righe[validi[0]]['time']} → {righe[validi[-1]]['time']}  ({len(validi)} giorni)")
    print("Ipotesi: ACCUMULO (più monete fuori) → su ; DISTRIBUZIONE (tornano su exchange) → giù")

    acc, dist, base = gruppi(validi, soglia, righe)
    print(f"\nEventi: accumulo (z≥+{soglia}) = {len(acc)}  |  distribuzione (z≤−{soglia}) = {len(dist)}")

    stampa_tabella(acc, dist, base, righe)
    stampa_split(validi, soglia, righe)
    if flag_fin:
        amp, passo = (int(x) for x in flag_fin.split(":"))
        stampa_finestre(validi, soglia, righe, amp, passo)
    print("\n" + "=" * 68)


if __name__ == "__main__":
    main()
