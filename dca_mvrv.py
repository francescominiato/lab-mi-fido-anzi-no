"""
lab/dca_mvrv.py — Il test che chiude il cerchio: il DCA modulato su MVRV
batte il DCA semplice?

Idea: invece di versare sempre la stessa cifra, versi di PIÙ quando MVRV è basso
(mercato sotto il costo base = zona di accumulo) e — opzionalmente — di MENO quando
è alto. Niente look-ahead: il moltiplicatore dipende solo dal MVRV di QUEL giorno.

Confronto EQUO = prezzo medio di acquisto (€ versati / BTC ottenuti): a parità di
euro spesi, chi compra BTC a prezzo medio più basso accumula più BTC. Mostro anche
quanti euro in più versa il modulato (serve avere quel capitale nei momenti giusti).

Strategie:
  • Semplice      : 1× sempre (DCA classico)
  • Accumulo+     : 1× neutro, 2× se MVRV<1.5, 3× se MVRV<1   (non scende MAI sotto 1×)
  • Accumulo±     : come sopra, ma 0.5× se MVRV≥2.5 (riduce quando è caro)

Uso:
    .venv/bin/python -m lab.dca_mvrv
"""

import csv
import os

QUI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(QUI), "data", "onchain_btc.csv")


def mult_semplice(m):
    return 1.0


def mult_accumulo_plus(m):
    if m < 1.0:
        return 3.0
    if m < 1.5:
        return 2.0
    return 1.0


def mult_accumulo_pm(m):
    if m < 1.0:
        return 3.0
    if m < 1.5:
        return 2.0
    if m < 2.5:
        return 1.0
    return 0.5


STRATEGIE = [("Semplice (1×)", mult_semplice),
             ("Accumulo+ (1/2/3×)", mult_accumulo_plus),
             ("Accumulo± (.5/1/2/3×)", mult_accumulo_pm)]


def carica():
    righe = []
    with open(DATA, newline="") as f:
        for r in csv.DictReader(f):
            p, m = r["price_usd"], r["mvrv"]
            if p == "" or m == "":
                continue
            righe.append({"anno": int(r["time"][:4]), "price": float(p), "mvrv": float(m)})
    return righe


def simula(righe, mult_fn, anno_da):
    """Versa ogni giorno 'mult' unità di euro; ritorna (euro, btc, prezzo_medio)."""
    euro = btc = 0.0
    for r in righe:
        if r["anno"] < anno_da:
            continue
        w = mult_fn(r["mvrv"])
        euro += w
        btc += w / r["price"]
    return euro, btc, (euro / btc if btc else None)


def periodo(righe, anno_da, etichetta):
    print(f"\n{etichetta}")
    base_euro, base_btc, base_pm = simula(righe, mult_semplice, anno_da)
    print(f"{'Strategia':<24}{'€ versati(rel)':>15}{'prezzo medio':>15}{'BTC in più':>13}")
    print("-" * 67)
    for nome, fn in STRATEGIE:
        euro, btc, pm = simula(righe, fn, anno_da)
        euro_rel = euro / base_euro
        # BTC in più a PARITÀ di euro = quanto rende meglio il prezzo medio
        btc_piu = (base_pm / pm - 1) * 100 if pm else 0
        segno = "—" if nome.startswith("Semplice") else f"{btc_piu:+.1f}%"
        print(f"{nome:<24}{euro_rel:>14.2f}x${pm:>13,.0f}{segno:>13}")


def main():
    righe = carica()
    print("=" * 67)
    print("DCA MODULATO SU MVRV vs DCA SEMPLICE")
    print("=" * 67)
    print('"BTC in più" = BTC extra a PARITÀ di euro spesi (grazie al prezzo medio più basso).')
    print('"€ versati(rel)" = quanti euro versa in totale vs il semplice (serve quel capitale).')

    a0 = righe[0]["anno"]
    for anno in [a0, 2015, 2018, 2021]:
        if anno < a0:
            continue
        periodo(righe, anno, f"PERIODO: da {anno} a fine ({righe[-1]['anno']})")
    print("\n" + "=" * 67)


if __name__ == "__main__":
    main()
