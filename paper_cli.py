"""
Ponte verso il paper trading UFFICIALE di Kraken (`kraken paper`).

Questo e' il "passo di diploma": quando hai scelto la TUA unica strategia, usi
questo per sapere cosa dice ORA il segnale, e poi esegui l'ordine sul conto
paper ufficiale di Kraken (identico al reale, ma a soldi finti).

Uso:
  python -m lab.paper_cli segnale ema      # cosa dice ora la strategia EMA?
  python -m lab.paper_cli stato            # mostra il P&L del conto paper Kraken

Per operare davvero sul conto paper usa direttamente la CLI, p.es.:
  kraken paper init --balance 10000
  kraken paper buy  XBTUSD 0.01
  kraken paper sell XBTUSD 0.01
  kraken paper status
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lab import config
from lab.data import fetch_candles, fetch_last_price
from lab.strategies import STRATEGIES, signal_label


def run_paper(*args: str) -> dict:
    """Esegue `kraken paper ... -o json` e restituisce il risultato parsato."""
    binary = os.path.expanduser(config.KRAKEN_BIN)
    cmd = [binary, "paper", *args, "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "comando paper fallito")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def current_signal(strategy_key: str) -> None:
    """Stampa il segnale attuale di UNA strategia, sui prezzi reali di adesso."""
    strat = next((s for s in STRATEGIES if s.key == strategy_key), None)
    if strat is None:
        keys = ", ".join(s.key for s in STRATEGIES)
        print(f"Strategia '{strategy_key}' sconosciuta. Disponibili: {keys}")
        return

    candles = fetch_candles()
    price = fetch_last_price()
    positions, _ = strat.func(candles)
    pos_now = positions[-1]
    pos_prev = positions[-2] if len(positions) >= 2 else 0
    signal = signal_label(pos_prev, pos_now)

    print(f"\nStrategia: {strat.name} — {strat.description}")
    print(f"Prezzo {config.PAIR} ora: {config.CURRENCY}{price:,.1f}")
    print(f"Posizione attuale: {'DENTRO' if pos_now == 1 else 'FUORI'}")
    print(f">>> SEGNALE: {signal}\n")
    if signal == "COMPRA":
        print("Suggerimento: kraken paper buy XBTUSD <quantita>")
    elif signal == "VENDI":
        print("Suggerimento: kraken paper sell XBTUSD <quantita>")
    else:
        print("Nessuna azione: nessun nuovo ingresso/uscita su questa candela.")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    comando = sys.argv[1]
    if comando == "segnale" and len(sys.argv) >= 3:
        current_signal(sys.argv[2])
    elif comando == "stato":
        print(json.dumps(run_paper("status"), indent=2, ensure_ascii=False))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
