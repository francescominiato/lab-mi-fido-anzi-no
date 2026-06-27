"""
Simulatore di paper trading forex EUR/USD — locale, a rischio zero.

Nessun account broker: il PREZZO è reale (preso live da Yahoo Finance), mentre il
conto, le posizioni e i COSTI sono simulati in casa, esattamente nello spirito del
`kraken paper`. L'utente scrive in linguaggio naturale, il simulatore traduce in comandi.

I costi sono MODELLATI (stime realistiche, NON tariffe reali di un broker):
  - spread:  SPREAD_PIP pip su ogni giro (entri all'ask, esci al bid);
  - swap:    SWAP_ANNUAL_PCT %/anno (carry), addebitato per ogni notte che la
             posizione resta aperta oltre le ~21:00 UTC (per l'intraday ~mai).
Sono dichiarati e mostrati a ogni `status`/`net`: vanno ricordati come stime.

Solo ordini a MERCATO: il simulatore non sorveglia il prezzo, quindi non esistono
ordini limite "pendenti" (servirebbe un broker che li tiene). Opero quando mi scrivi.

Uso:
  python -m lab.fx_paper price                 # bid/ask/spread EUR/USD live
  python -m lab.fx_paper buy 250               # apre/aumenta long ~250€
  python -m lab.fx_paper sell 250              # apre short / riduce-chiude long
  python -m lab.fx_paper close                 # chiude tutta la posizione
  python -m lab.fx_paper status                # cassa, P&L, equity stimata
  python -m lab.fx_paper net                   # equity netta chiudendo ORA
  python -m lab.fx_paper reset                 # azzera il conto a 10.000€
"""

import csv
import datetime as dt
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- Costanti ---------------------------------------------------------------
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(_ROOT, "data", "fx_paper_state.json")
LOG_FILE = os.path.join(_ROOT, "data", "fx_paper_log.csv")
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1m&range=1d"

CAPITALE_INIZIALE = 10000.0    # € di partenza del conto demo locale
PIP = 0.0001                  # un pip su EUR/USD
SPREAD_PIP = 0.6              # spread totale modellato (retail tipico)
SWAP_ANNUAL_PCT = -1.8        # carry annuo per un LONG EUR/USD (negativo = costo)
ROLLOVER_HOUR_UTC = 21       # ~chiusura giornaliera: oltre = una notte di swap


def fetch_mid():
    """Unico punto di rete: prezzo mid EUR/USD live da Yahoo. Mockato nei test."""
    req = urllib.request.Request(YAHOO_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])


# --- Stato del conto --------------------------------------------------------
def default_state():
    """Conto vuoto: solo cassa, nessuna posizione."""
    return {"saldo_eur": CAPITALE_INIZIALE, "posizione": None}


def save_state(state, path=STATE_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f)


def load_state(path=STATE_FILE):
    if not os.path.exists(path):
        return default_state()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# --- Funzioni pure di prezzo e costi ----------------------------------------
def parse_price(s):
    """Converte una stringa prezzo (accetta la virgola italiana) in float."""
    return float(str(s).strip().replace(",", "."))


def spread_price():
    """Lo spread modellato espresso in prezzo (non in pip)."""
    return SPREAD_PIP * PIP


def prezzo_exec(mid, lato):
    """Prezzo di esecuzione: il BUY paga l'ask (mid + mezzo spread), il SELL incassa il bid."""
    mezzo = spread_price() / 2.0
    return mid + mezzo if lato == "BUY" else mid - mezzo


def pnl_di(direction, prezzo_entrata, prezzo_uscita, size):
    """P&L in € di una posizione: esposizione × variazione percentuale (col segno del lato)."""
    var = (prezzo_uscita - prezzo_entrata) / prezzo_entrata
    return size * var if direction == "BUY" else size * (-var)


def pnl_non_realizzato(pos, prezzo):
    """P&L non realizzato della posizione aperta, valutata a `prezzo`."""
    if not pos:
        return 0.0
    return pnl_di(pos["direction"], pos["prezzo_entrata"], prezzo, pos["size"])


def applica_ordine(pos, lato, size, prezzo):
    """Applica un ordine a mercato alla posizione netta. Ritorna (nuova_pos, pnl_realizzato).

    Gestisce: apertura, aumento (media il prezzo), riduzione/chiusura, inversione.
    `pos` è None oppure {'direction','size','prezzo_entrata'}.
    """
    if not pos:
        return {"direction": lato, "size": size, "prezzo_entrata": prezzo}, 0.0
    if pos["direction"] == lato:
        tot = pos["size"] + size
        pe = (pos["prezzo_entrata"] * pos["size"] + prezzo * size) / tot
        return {"direction": lato, "size": tot, "prezzo_entrata": pe}, 0.0
    # lato opposto: chiude (in parte, del tutto, o inverte)
    if size < pos["size"] - 1e-9:
        pnl = pnl_di(pos["direction"], pos["prezzo_entrata"], prezzo, size)
        return {**pos, "size": pos["size"] - size}, pnl
    pnl = pnl_di(pos["direction"], pos["prezzo_entrata"], prezzo, pos["size"])
    if abs(size - pos["size"]) <= 1e-9:
        return None, pnl
    residuo = size - pos["size"]
    return {"direction": lato, "size": residuo, "prezzo_entrata": prezzo}, pnl


def notti_rollover(open_ts, now_ts, hour_utc=ROLLOVER_HOUR_UTC):
    """Quante soglie di rollover (~21 UTC) sono cadute tra l'apertura e ora."""
    apertura = dt.datetime.fromtimestamp(open_ts, dt.timezone.utc)
    adesso = dt.datetime.fromtimestamp(now_ts, dt.timezone.utc)
    soglia = apertura.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if apertura >= soglia:
        soglia += dt.timedelta(days=1)
    n = 0
    while soglia <= adesso:
        n += 1
        soglia += dt.timedelta(days=1)
    return n


def swap_maturato(pos, now_ts):
    """Swap (carry) accumulato dalla posizione: negativo = costo. Long paga, short incassa."""
    if not pos:
        return 0.0
    notti = notti_rollover(pos.get("ts_apertura", now_ts), now_ts)
    swap_per_notte = pos["size"] * (SWAP_ANNUAL_PCT / 100.0) / 365.0
    if pos["direction"] == "SELL":
        swap_per_notte = -swap_per_notte
    return swap_per_notte * notti


# --- Resoconti (funzioni pure) ----------------------------------------------
def _riga_costi():
    return f"(costi modellati: spread {SPREAD_PIP:g} pip · swap {SWAP_ANNUAL_PCT:g}%/anno)"


def format_status(state, mid, now_ts):
    """Testo del conto: cassa, posizione, P&L al mid, swap maturato, equity stimata."""
    saldo = state["saldo_eur"]
    pos = state["posizione"]
    pnl_nr = pnl_non_realizzato(pos, mid)
    swap = swap_maturato(pos, now_ts)
    equity = saldo + pnl_nr + swap
    righe = [f"Cassa: €{saldo:,.2f}"]
    if not pos:
        righe.append("Nessuna posizione aperta.")
    else:
        righe.append(
            f"Posizione: {pos['direction']} {pos['size']:g}€ @ {pos['prezzo_entrata']:.5f} "
            f"(mid ora {mid:.5f})"
        )
        righe.append(f"P&L non realizzato (al mid): €{pnl_nr:+,.2f}")
        if swap:
            righe.append(f"Swap maturato: €{swap:+,.2f}")
    righe.append(f"Equity stimata: €{equity:,.2f}")
    righe.append(_riga_costi())
    return "\n".join(righe)


def simulate_net(state, mid, now_ts):
    """Equity NETTA chiudendo tutto ORA: valuta al prezzo di chiusura reale (col spread) + swap."""
    saldo = state["saldo_eur"]
    pos = state["posizione"]
    if not pos:
        return {"valore_netto": saldo, "costo_uscita": 0.0, "swap": 0.0}
    lato_chiusura = "SELL" if pos["direction"] == "BUY" else "BUY"
    prezzo_ch = prezzo_exec(mid, lato_chiusura)
    pnl_chiusura = pnl_non_realizzato(pos, prezzo_ch)
    pnl_mid = pnl_non_realizzato(pos, mid)
    swap = swap_maturato(pos, now_ts)
    valore_netto = saldo + pnl_chiusura + swap
    return {"valore_netto": valore_netto, "costo_uscita": pnl_mid - pnl_chiusura, "swap": swap}


# --- Registro ---------------------------------------------------------------
LOG_COLUMNS = ["ts", "lato", "importo_eur", "size", "prezzo", "spread", "pnl_realizzato", "saldo"]


def log_row(row, path=LOG_FILE):
    """Appende una riga al registro CSV, scrivendo l'header se il file è nuovo."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    nuovo = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        if nuovo:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in LOG_COLUMNS})


# --- Azioni -----------------------------------------------------------------
def _ora():
    return int(dt.datetime.now(dt.timezone.utc).timestamp())


def esegui_ordine(lato, importo_eur, state_path=STATE_FILE, log_path=LOG_FILE):
    """Esegue un ordine a mercato sul conto locale e logga. `size` = importo in € (esposizione)."""
    mid = fetch_mid()
    prezzo = prezzo_exec(mid, lato)
    size = round(importo_eur, 2)
    state = load_state(path=state_path)
    vecchia = state["posizione"]
    pos2, pnl = applica_ordine(vecchia, lato, size, prezzo)
    now = _ora()
    if pos2:
        stessa = vecchia and vecchia.get("direction") == pos2["direction"] and vecchia.get("ts_apertura")
        pos2["ts_apertura"] = vecchia["ts_apertura"] if stessa else now
    else:
        # chiusura totale: realizza anche lo swap maturato sulla vecchia posizione
        pnl += swap_maturato(vecchia, now)
    state["posizione"] = pos2
    state["saldo_eur"] = round(state["saldo_eur"] + pnl, 2)
    save_state(state, path=state_path)
    log_row({
        "ts": now, "lato": lato, "importo_eur": importo_eur, "size": size,
        "prezzo": round(prezzo, 5), "spread": SPREAD_PIP, "pnl_realizzato": round(pnl, 2),
        "saldo": state["saldo_eur"],
    }, path=log_path)
    return {"mid": mid, "prezzo": prezzo, "pnl_realizzato": pnl, "state": state}


def chiudi_tutto(state_path=STATE_FILE, log_path=LOG_FILE):
    """Chiude l'intera posizione con un ordine di verso opposto."""
    state = load_state(path=state_path)
    pos = state["posizione"]
    if not pos:
        return None
    lato = "SELL" if pos["direction"] == "BUY" else "BUY"
    return esegui_ordine(lato, pos["size"], state_path=state_path, log_path=log_path)


def reset_conto(balance=CAPITALE_INIZIALE, state_path=STATE_FILE):
    """Azzera posizioni e riporta la cassa a `balance`."""
    state = {"saldo_eur": round(balance, 2), "posizione": None}
    save_state(state, path=state_path)
    return state


# --- CLI ---------------------------------------------------------------------
def parse_args(argv):
    """Traduce gli argomenti CLI in (comando, kwargs). Niente I/O qui (testabile)."""
    if not argv:
        return "help", {}
    cmd = argv[0]
    rest = argv[1:]

    def opt(nome):
        return rest[rest.index(nome) + 1] if nome in rest else None

    if cmd in ("buy", "sell"):
        return cmd, {"importo_eur": float(rest[0])}
    if cmd == "reset":
        bal = opt("--balance")
        return cmd, {"balance": float(bal) if bal else CAPITALE_INIZIALE}
    return cmd, {}


def main():
    cmd, kwargs = parse_args(sys.argv[1:])
    if cmd == "price":
        mid = fetch_mid()
        bid, ask = prezzo_exec(mid, "SELL"), prezzo_exec(mid, "BUY")
        print(f"EUR/USD  mid {mid:.5f}  bid {bid:.5f}  ask {ask:.5f}  "
              f"spread {SPREAD_PIP:g} pip (modellato)")
    elif cmd in ("buy", "sell"):
        lato = "BUY" if cmd == "buy" else "SELL"
        r = esegui_ordine(lato, kwargs["importo_eur"])
        print(f"Eseguito {lato} {kwargs['importo_eur']:g}€ @ {r['prezzo']:.5f} "
              f"(mid {r['mid']:.5f})")
        if r["pnl_realizzato"]:
            print(f"P&L realizzato: €{r['pnl_realizzato']:+,.2f}")
        print(format_status(r["state"], r["mid"], _ora()))
    elif cmd == "close":
        r = chiudi_tutto()
        if r is None:
            print("Nessuna posizione da chiudere.")
        else:
            print(f"Chiusa posizione @ {r['prezzo']:.5f}. P&L realizzato: €{r['pnl_realizzato']:+,.2f}")
            print(format_status(r["state"], r["mid"], _ora()))
    elif cmd == "status":
        mid = fetch_mid()
        print(format_status(load_state(), mid, _ora()))
    elif cmd == "net":
        mid = fetch_mid()
        n = simulate_net(load_state(), mid, _ora())
        print(format_status(load_state(), mid, _ora()))
        print(f"Valore netto (chiudendo ORA): €{n['valore_netto']:,.2f} "
              f"(costo uscita €{n['costo_uscita']:,.2f}, swap €{n['swap']:+,.2f})")
    elif cmd == "reset":
        reset_conto(kwargs["balance"])
        print(f"Conto demo locale azzerato a €{kwargs['balance']:,.2f}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
