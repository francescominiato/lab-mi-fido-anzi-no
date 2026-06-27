"""
lab/onchain_study.py — Event study sulla DETERMINANTE netflow exchange.

Primo esperimento "fuori dal grafico": invece di un pattern di prezzo, studiamo una
CAUSA (quanti BTC entrano/escono dagli exchange) e vediamo cosa fa il prezzo dopo.

- Netflow = BTC entrati sugli exchange − BTC usciti, in BTC NATIVO (non in dollari):
  così la metrica NON è contaminata dal prezzo → causa pulita.
- "Estremo" = z-score su finestra mobile di 90 giorni (confrontabile in ogni epoca).
  Lo z guarda solo i 90 giorni PRECEDENTI → niente look-ahead.
    • DEFLUSSO estremo  (z ≤ −soglia): BTC lasciano gli exchange = accumulo/custodia → ipotesi SU.
    • AFFLUSSO estremo  (z ≥ +soglia): BTC verso gli exchange = vendita potenziale  → ipotesi GIÙ.
- Misura il rendimento del PREZZO a +5/+10/+30 giorni, prob. prezzo su, MAE/MFE,
  sempre confrontati con la BASELINE (tutti i giorni). Verifica di stabilità: SPLIT 70/30.

Uso:
    .venv/bin/python -m lab.onchain_study [finestra_z=90] [soglia_z=2]
"""

import csv
import os
import statistics
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(QUI), "data", "onchain_btc.csv")

ORIZZONTI = [5, 10, 30]          # giorni dopo l'evento
ORIZ_MAX = max(ORIZZONTI)


def carica():
    """Carica le righe con prezzo e netflow nativo validi."""
    righe = []
    with open(DATA, newline="") as f:
        for r in csv.DictReader(f):
            p, nf = r["price_usd"], r["netflow_ntv"]
            if p == "" or nf == "":
                continue
            righe.append({"time": r["time"], "price": float(p), "nf": float(nf)})
    return righe


def calcola_z(righe, fin):
    """z-score del netflow sui 'fin' giorni precedenti (no look-ahead)."""
    for i, r in enumerate(righe):
        if i < fin:
            r["z"] = None
            continue
        prev = [righe[j]["nf"] for j in range(i - fin, i)]
        sd = statistics.pstdev(prev)
        r["z"] = (r["nf"] - statistics.fmean(prev)) / sd if sd > 0 else None


def metriche(indici, righe):
    """Rendimenti del prezzo (mediana/media), prob. su, MAE/MFE per un gruppo di giorni."""
    n_tot = len(righe)
    out = {"n": len(indici)}
    for k in ORIZZONTI:
        rets = [righe[i + k]["price"] / righe[i]["price"] - 1
                for i in indici if i + k < n_tot]
        out[f"med{k}"] = statistics.median(rets) if rets else None
        out[f"avg{k}"] = statistics.fmean(rets) if rets else None
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
    return f"{x * 100:+.2f}%" if x is not None else "    —"


def gruppi(indici, soglia, righe):
    """Separa un insieme di indici in deflusso / afflusso / baseline(tutti)."""
    defl = [i for i in indici if righe[i]["z"] <= -soglia]
    affl = [i for i in indici if righe[i]["z"] >= soglia]
    return defl, affl, indici


def stampa_tabella(defl, affl, base, righe):
    md, ma, mb = (metriche(g, righe) for g in (defl, affl, base))
    print(f"\n{'Metrica':<22}{'Deflusso z≤−s':>16}{'Afflusso z≥+s':>16}{'Baseline':>14}")
    print("-" * 68)
    print(f"{'n. giorni':<22}{md['n']:>16}{ma['n']:>16}{mb['n']:>14}")
    for k in ORIZZONTI:
        print(f"{'Ret mediano +' + str(k) + 'g':<22}"
              f"{_pct(md[f'med{k}']):>16}{_pct(ma[f'med{k}']):>16}{_pct(mb[f'med{k}']):>14}")
    print(f"{'Ret medio +30g':<22}{_pct(md['avg30']):>16}{_pct(ma['avg30']):>16}{_pct(mb['avg30']):>14}")
    print(f"{'Prob. prezzo su +30g':<22}"
          f"{(str(round(md['prob'],1))+'%' if md['prob'] is not None else '—'):>16}"
          f"{(str(round(ma['prob'],1))+'%' if ma['prob'] is not None else '—'):>16}"
          f"{(str(round(mb['prob'],1))+'%' if mb['prob'] is not None else '—'):>14}")
    print(f"{'MAE medio (30g)':<22}{_pct(md['mae']):>16}{_pct(ma['mae']):>16}{_pct(mb['mae']):>14}")
    print(f"{'MFE medio (30g)':<22}{_pct(md['mfe']):>16}{_pct(ma['mfe']):>16}{_pct(mb['mfe']):>14}")


def stampa_split(validi, soglia, righe, frazione=0.70):
    taglio = int(len(validi) * frazione)
    parti = [("IN-SAMPLE (primo 70%)", validi[:taglio]),
             ("OUT-OF-SAMPLE (ultimo 30%)", validi[taglio:])]
    print("\n" + "=" * 68)
    print("VERIFICA DI STABILITÀ — SPLIT 70/30 (regge nel pezzo mai visto?)")
    print("=" * 68)
    for nome, idx in parti:
        if not idx:
            continue
        defl, affl, base = gruppi(idx, soglia, righe)
        md, ma, mb = (metriche(g, righe) for g in (defl, affl, base))
        intervallo = f"{righe[idx[0]]['time']} → {righe[idx[-1]]['time']}"
        print(f"\n{nome}   ({intervallo})")
        for nm, m in [("Deflusso z≤−s", md), ("Afflusso z≥+s", ma), ("Baseline", mb)]:
            avviso = "  ⚠ pochi eventi" if (m['n'] < 30 and nm != "Baseline") else ""
            prob = f"{m['prob']:.1f}%" if m['prob'] is not None else "—"
            print(f"  {nm:<16} n={m['n']:>4}   "
                  f"ret mediano +30g {_pct(m['med30'])}   prob su {prob}{avviso}")


def stampa_finestre(validi, soglia, righe, ampiezza=3, passo=1):
    """Mostra il segnale finestra per finestra (es. 3 anni che scorrono): regge in OGNI epoca?"""
    anni = sorted({int(righe[i]["time"][:4]) for i in validi})
    print("\n" + "=" * 68)
    print(f"FINESTRE SCORREVOLI ({ampiezza} anni, passo {passo}) — regge in OGNI epoca?")
    print("=" * 68)
    print("Δ = scarto della prob. 'prezzo su +30g' vs baseline.")
    print("Ipotesi: AFFLUSSO Δ negativo (debolezza) · DEFLUSSO Δ positivo (forza)\n")

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
        defl, affl, base = gruppi(idx, soglia, righe)
        md, ma, mb = (metriche(g, righe) for g in (defl, affl, base))
        if mb["prob"] is None:
            continue
        print(f"  {start}-{end - 1}  base {mb['prob']:>5.1f}%   "
              f"AFFL {cella(ma, mb['prob'])}   DEFL {cella(md, mb['prob'])}")


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
    print("EVENT STUDY ON-CHAIN — NETFLOW EXCHANGE (causa, non grafico)")
    print("=" * 68)
    print(f"Netflow in BTC nativo | z-score su {fin} giorni | soglia ±{soglia}")
    print(f"Periodo analizzato: {righe[validi[0]]['time']} → {righe[validi[-1]]['time']}"
          f"  ({len(validi)} giorni)")
    print("Ipotesi: DEFLUSSO (accumulo) → su ;  AFFLUSSO (vendita) → giù")

    defl, affl, base = gruppi(validi, soglia, righe)
    print(f"\nEventi: deflusso estremo (z≤−{soglia}) = {len(defl)}  |  "
          f"afflusso estremo (z≥+{soglia}) = {len(affl)}")

    stampa_tabella(defl, affl, base, righe)
    stampa_split(validi, soglia, righe)
    if flag_fin:
        amp, passo = (int(x) for x in flag_fin.split(":"))
        stampa_finestre(validi, soglia, righe, amp, passo)
    print("\n" + "=" * 68)


if __name__ == "__main__":
    main()
