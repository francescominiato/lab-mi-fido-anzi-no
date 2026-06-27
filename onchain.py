"""
lab/onchain.py — Primo mattone della ricerca "fuori dal grafico".

Scarica i dati on-chain GRATUITI di Coin Metrics Community (file csv/btc.csv del
repo github coinmetrics/data), estrae le colonne che ci servono, calcola il
NETFLOW exchange (= flussi IN − flussi OUT) e salva un CSV pulito in data/.

Poi stampa un riepilogo onesto della COPERTURA: quante righe abbiamo davvero per
ogni metrica e — soprattutto — DA QUANDO iniziano i flussi exchange (nel 2009 gli
exchange non esistevano, quindi quella serie parte più tardi del prezzo).

Nessuna dipendenza esterna: solo libreria standard. Nessuna API key.

Uso:
    .venv/bin/python -m lab.onchain          # usa la cache se presente
    .venv/bin/python -m lab.onchain --fresh  # forza il ri-download
"""

import csv
import os
import sys
import urllib.request

# --- Percorsi (assoluti, basati sulla posizione di questo file) ---
QUI = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(QUI), "data")
RAW_CSV = os.path.join(DATA_DIR, "coinmetrics_btc.csv")          # dato grezzo scaricato
CLEAN_CSV = os.path.join(DATA_DIR, "onchain_btc.csv")            # nostro CSV pulito

URL = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/btc.csv"

# Nomi delle colonne Coin Metrics che ci interessano (lette per NOME, non per
# posizione, così se cambiano l'ordine non ci rompiamo).
COL_DATA = "time"
COL_PREZZO = "PriceUSD"
COL_MVRV = "CapMVRVCur"          # Market Value / Realized Value, già pronto
COL_FLOW_IN_USD = "FlowInExUSD"  # BTC entrati sugli exchange (in $)
COL_FLOW_OUT_USD = "FlowOutExUSD"
COL_FLOW_IN_NTV = "FlowInExNtv"  # idem, in BTC
COL_FLOW_OUT_NTV = "FlowOutExNtv"
COL_SUPPLY = "SplyCur"           # supply totale in circolazione (BTC)
COL_SUPPLY_EX = "SplyExNtv"      # supply detenuta SUGLI exchange (BTC) — dal 2011


def scarica(forza=False):
    """Scarica il CSV grezzo di Coin Metrics, riusando la cache se già presente."""
    if os.path.exists(RAW_CSV) and not forza:
        print(f"• Uso la cache già presente: {RAW_CSV}")
        return
    print(f"• Scarico i dati on-chain da Coin Metrics...\n  {URL}")
    os.makedirs(DATA_DIR, exist_ok=True)
    urllib.request.urlretrieve(URL, RAW_CSV)
    print(f"  salvato in {RAW_CSV}")


def _num(valore):
    """Converte una stringa in float; '' o spazi -> None (dato mancante)."""
    if valore is None or valore.strip() == "":
        return None
    try:
        return float(valore)
    except ValueError:
        return None


def elabora():
    """Legge il grezzo, calcola il netflow, scrive il CSV pulito e lo restituisce."""
    with open(RAW_CSV, newline="") as f:
        lettore = csv.DictReader(f)
        colonne = lettore.fieldnames or []

        # Controllo di sicurezza: ci sono le colonne che ci aspettiamo?
        attese = [COL_DATA, COL_PREZZO, COL_MVRV, COL_FLOW_IN_USD, COL_FLOW_OUT_USD]
        mancanti = [c for c in attese if c not in colonne]
        if mancanti:
            print("✗ ATTENZIONE: mancano colonne attese:", mancanti)
            print("  Colonne disponibili nel file:")
            print("  " + ", ".join(colonne))
            sys.exit(1)

        righe = []
        for r in lettore:
            prezzo = _num(r.get(COL_PREZZO))
            mvrv = _num(r.get(COL_MVRV))
            fin_usd = _num(r.get(COL_FLOW_IN_USD))
            fout_usd = _num(r.get(COL_FLOW_OUT_USD))
            fin_ntv = _num(r.get(COL_FLOW_IN_NTV))
            fout_ntv = _num(r.get(COL_FLOW_OUT_NTV))

            # Netflow = quanto è entrato MENO quanto è uscito.
            # Positivo = più BTC verso gli exchange (potenziale pressione di vendita).
            net_usd = (fin_usd - fout_usd) if (fin_usd is not None and fout_usd is not None) else None
            net_ntv = (fin_ntv - fout_ntv) if (fin_ntv is not None and fout_ntv is not None) else None

            # Supply NON sugli exchange = totale − quella sugli exchange (proxy "illiquid supply")
            supply = _num(r.get(COL_SUPPLY))
            sply_ex = _num(r.get(COL_SUPPLY_EX))
            sply_nonex = (supply - sply_ex) if (supply is not None and sply_ex is not None) else None

            righe.append({
                "time": r.get(COL_DATA),
                "price_usd": prezzo,
                "mvrv": mvrv,
                "flow_in_usd": fin_usd,
                "flow_out_usd": fout_usd,
                "netflow_usd": net_usd,
                "netflow_ntv": net_ntv,
                "supply": supply,
                "sply_ex": sply_ex,
                "sply_nonex": sply_nonex,
            })

    # Scrive il CSV pulito
    campi = ["time", "price_usd", "mvrv", "flow_in_usd", "flow_out_usd",
             "netflow_usd", "netflow_ntv", "supply", "sply_ex", "sply_nonex"]
    with open(CLEAN_CSV, "w", newline="") as f:
        scrittore = csv.DictWriter(f, fieldnames=campi)
        scrittore.writeheader()
        for r in righe:
            scrittore.writerow(r)

    return righe


def _copertura(righe, chiave):
    """Restituisce (n_validi, prima_data, ultima_data) per una metrica."""
    valide = [r for r in righe if r[chiave] is not None]
    if not valide:
        return 0, None, None
    return len(valide), valide[0]["time"], valide[-1]["time"]


def riepilogo(righe):
    """Stampa un quadro onesto di quanto dato abbiamo, metrica per metrica."""
    tot = len(righe)
    print("\n" + "=" * 64)
    print("RIEPILOGO COPERTURA DATI ON-CHAIN (Coin Metrics Community)")
    print("=" * 64)
    print(f"Righe totali: {tot}   "
          f"({righe[0]['time']} → {righe[-1]['time']})")
    print(f"CSV pulito salvato in: {CLEAN_CSV}\n")

    print(f"{'Metrica':<16}{'Righe valide':>14}{'%':>7}{'Dalla data':>14}{'Alla data':>14}")
    print("-" * 64)
    for etichetta, chiave in [("Prezzo USD", "price_usd"),
                              ("MVRV", "mvrv"),
                              ("Netflow USD", "netflow_usd"),
                              ("Netflow BTC", "netflow_ntv")]:
        n, prima, ultima = _copertura(righe, chiave)
        pct = (100 * n / tot) if tot else 0
        print(f"{etichetta:<16}{n:>14}{pct:>6.0f}%{str(prima):>14}{str(ultima):>14}")

    # Anteprima degli ultimi valori utili (per un controllo a occhio)
    print("\nUltimi 3 giorni con netflow disponibile:")
    con_net = [r for r in righe if r["netflow_usd"] is not None][-3:]
    for r in con_net:
        seg = "IN " if r["netflow_usd"] > 0 else "OUT"
        mvrv_txt = f"{r['mvrv']:.2f}" if r["mvrv"] is not None else "—"
        print(f"  {r['time']}  prezzo ${r['price_usd']:>10,.0f}  "
              f"MVRV {mvrv_txt:>5}  "
              f"netflow {seg} ${abs(r['netflow_usd']):>14,.0f}")
    print("=" * 64)


def main():
    forza = "--fresh" in sys.argv
    scarica(forza=forza)
    righe = elabora()
    riepilogo(righe)


if __name__ == "__main__":
    main()
