"""
lab/cruscotto.py — In che zona siamo OGGI? (termometro MVRV per l'accumulo)

Dice in che zona di valutazione si trova BTC e quanto accumulare di conseguenza.

Fonte del MVRV:
  • se è impostata BGEO_KEY → usa BGeometrics (dato FRESCO, aggiornato a ieri);
  • altrimenti → ripiega sul nostro data/onchain_btc.csv (Coin Metrics, con qualche
    settimana di lag). Per aggiornarlo: prima lancia `python -m lab.onchain --fresh`.

NON è un oracolo: è un aiuto all'accumulo con le 5 cautele del DISTILLATO (§9).

Uso:
    BGEO_KEY=... .venv/bin/python -m lab.cruscotto      # dato fresco
    .venv/bin/python -m lab.cruscotto                   # dal CSV (con lag)
"""

import csv
import json
import os
import urllib.request

QUI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(QUI), "data", "onchain_btc.csv")


def ultimo_csv():
    """Ultima riga del CSV con prezzo e MVRV validi (fonte di ripiego + prezzo)."""
    ultima = None
    with open(DATA, newline="") as f:
        for r in csv.DictReader(f):
            if r["mvrv"] != "" and r["price_usd"] != "":
                ultima = r
    return ultima


def mvrv_fresco():
    """MVRV più recente da BGeometrics, se c'è la key. Ritorna (data, mvrv) o None."""
    key = os.environ.get("BGEO_KEY")
    if not key:
        return None
    try:
        req = urllib.request.Request("https://api.bgeometrics.com/v1/mvrv",
                                     headers={"Authorization": f"Bearer {key}",
                                              "User-Agent": "lab-cruscotto/1"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            dati = json.load(resp)
        ultimo = dati[-1]
        return str(ultimo["d"])[:10], float(ultimo["mvrv"])
    except Exception:
        return None   # qualsiasi problema → ripiego silenzioso sul CSV


def zona(mvrv):
    """Ritorna (emoji, nome, moltiplicatore DCA suggerito, commento)."""
    if mvrv < 1.0:
        return ("🟢🟢", "FONDO / CAPITOLAZIONE", "3×",
                "Mercato sotto il costo medio degli holder. Storicamente la zona "
                "MIGLIORE per accumulare (a +180g su l'80%+ delle volte).")
    if mvrv < 1.5:
        return ("🟢", "ECONOMICA", "2×",
                "Ancora a buon mercato rispetto al costo base. Accumula un po' di più.")
    if mvrv < 2.5:
        return ("⚪", "NEUTRA", "1×",
                "Né a sconto né in euforia. Accumulo normale, come sempre.")
    return ("🟠", "CARA", "0,5×",
            "Sopra il costo base in modo marcato. Eventualmente versa meno — ma il "
            "lato 'euforia' è storicamente inaffidabile: NON vendere, semmai rallentare.")


def main():
    csvrow = ultimo_csv()
    if not csvrow:
        print("Nessun dato valido. Lancia prima: python -m lab.onchain --fresh")
        return

    fresco = mvrv_fresco()
    if fresco:
        data_mvrv, mvrv = fresco
        fonte = "BGeometrics (fresco)"
    else:
        data_mvrv, mvrv = csvrow["time"], float(csvrow["mvrv"])
        fonte = "Coin Metrics / CSV (può avere qualche settimana di lag)"

    prezzo = float(csvrow["price_usd"])
    em, nome, mult, commento = zona(mvrv)

    print("=" * 60)
    print("CRUSCOTTO ACCUMULO — termometro MVRV")
    print("=" * 60)
    print(f"MVRV al           : {data_mvrv}   (fonte: {fonte})")
    print(f"MVRV              : {mvrv:.2f}")
    print(f"Prezzo BTC        : ${prezzo:,.0f}   (al {csvrow['time']})")
    print(f"\n{em}  ZONA: {nome}")
    print(f"Accumulo suggerito: {mult} la quota base")
    print(f"\n{commento}")
    print("\n" + "-" * 60)
    print("⚠ Ricorda le 5 cautele (DISTILLATO §9): pochi episodi storici,")
    print("  scommessa sulla ripresa di BTC, segnale lento (6 mesi), lato")
    print("  euforia inaffidabile. È un aiuto all'accumulo, NON un oracolo.")
    print("  (MVRV = rapporto adimensionale: vale uguale in USD e in EUR.)")
    print("=" * 60)


if __name__ == "__main__":
    main()
