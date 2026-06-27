"""
lab/onchain_xcheck.py — Cross-check del MVRV: Coin Metrics vs BGeometrics.

Scopo: blindare la fonte. Due provider INDIPENDENTI che danno lo stesso MVRV →
ci fidiamo del segnale; se divergono, è un allarme.

Fonte 1: Coin Metrics (il nostro data/onchain_btc.csv, colonna mvrv).
Fonte 2: BGeometrics, endpoint https://api.bgeometrics.com/v1/mvrv
         auth via header  Authorization: Bearer <KEY>   (free tier: ~4 anni di storia).

⚠ Richiede la API key GRATUITA di BGeometrics (registrazione su bgeometrics.com).
   Lanciala passando la key da variabile d'ambiente (NON si scrive su file):

       BGEO_KEY=la_tua_key .venv/bin/python -m lab.onchain_xcheck

Esito atteso (giu 2026): scarto mediano ~0,7% → fonti concordi, MVRV affidabile.

Uso:
    BGEO_KEY=... .venv/bin/python -m lab.onchain_xcheck
"""

import csv
import json
import os
import statistics
import sys
import urllib.request

QUI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(QUI), "data", "onchain_btc.csv")
ENDPOINT = "https://api.bgeometrics.com/v1/mvrv"
SOGLIA_OK = 2.0   # scarto mediano % sotto il quale le fonti si considerano concordi


def mvrv_coinmetrics():
    out = {}
    with open(DATA, newline="") as f:
        for r in csv.DictReader(f):
            if r["mvrv"] not in ("", None):
                out[r["time"]] = float(r["mvrv"])
    return out


def mvrv_bgeometrics(key):
    """Scarica la serie MVRV. Record tipico: {'d':'YYYY-MM-DD','unixTs':..,'mvrv':..}."""
    req = urllib.request.Request(ENDPOINT, headers={
        "Authorization": f"Bearer {key}", "User-Agent": "lab-onchain/1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dati = json.load(resp)
    out = {}
    for it in dati:
        d = it.get("d") or it.get("date") or it.get("time")
        v = it.get("mvrv", it.get("value"))
        if d and v not in (None, ""):
            out[str(d)[:10]] = float(v)
    return out


def main():
    key = os.environ.get("BGEO_KEY")
    if not key:
        print("✗ Manca la API key. Registrati (gratis) su bgeometrics.com e lancia:")
        print("  BGEO_KEY=la_tua_key .venv/bin/python -m lab.onchain_xcheck")
        sys.exit(1)

    cm = mvrv_coinmetrics()
    try:
        bg = mvrv_bgeometrics(key)
    except Exception as e:
        print(f"✗ Errore nello scaricare da BGeometrics: {e}")
        sys.exit(1)

    comuni = sorted(set(cm) & set(bg))
    scarti = [abs(cm[d] - bg[d]) / cm[d] * 100 for d in comuni if cm[d] > 0]
    if not scarti:
        print("✗ Nessuna data in comune tra le due fonti.")
        sys.exit(1)

    mediano = statistics.median(scarti)
    print("=" * 60)
    print("CROSS-CHECK MVRV — Coin Metrics vs BGeometrics")
    print("=" * 60)
    print(f"Giorni confrontati : {len(comuni)}  ({comuni[0]} → {comuni[-1]})")
    print(f"Scarto medio       : {statistics.fmean(scarti):.2f}%")
    print(f"Scarto mediano     : {mediano:.2f}%")
    print(f"Scarto massimo     : {max(scarti):.2f}%")
    if mediano < SOGLIA_OK:
        print(f"\n✓ Le due fonti CONCORDANO (mediano < {SOGLIA_OK:.0f}%): MVRV affidabile.")
    else:
        print(f"\n⚠ Le due fonti DIVERGONO (mediano ≥ {SOGLIA_OK:.0f}%): indagare prima di fidarsi.")
    # ultimo dato BGeometrics (più fresco di Coin Metrics)
    ultima = max(bg)
    print(f"\nDato BGeometrics più recente: {ultima}  MVRV = {bg[ultima]:.2f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
