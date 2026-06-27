"""
Dashboard live "a tre finestre".

Tre pannelli affiancati, uno per strategia. Ogni pannello mostra, sui prezzi
REALI di Kraken aggiornati in tempo reale:
  - il segnale attuale: COMPRA / VENDI / MANTIENI / ASPETTA
  - i valori degli indicatori (EMA, RSI, canale)
  - se la strategia e' DENTRO o FUORI dal mercato
  - l'equity virtuale e il guadagno/perdita (vs partenza e vs "compra e tieni")

I segnali si basano sulle candele GIA' CHIUSE (niente sbirciate sul futuro).

Avvio:  python -m lab.dashboard      (oppure  python lab/dashboard.py)
Fermare: Ctrl+C
"""

import os
import sys
import time
from datetime import datetime

# Permette di lanciare lo script sia con -m lab.dashboard sia direttamente.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.columns import Columns
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from lab import config
from lab.data import Candle, fetch_candles, fetch_last_price
from lab.portfolio import buy_and_hold, run_backtest
from lab.strategies import STRATEGIES, signal_label

SIGNAL_STYLE = {
    "COMPRA": ("green", "📈"),
    "VENDI": ("red", "📉"),
    "MANTIENI": ("cyan", "✅"),
    "ASPETTA": ("yellow", "⏸"),
}


def _fmt(value, suffix: str = "") -> str:
    return f"{value:,.1f}{suffix}" if value is not None else "—"


def build_panel(strat, candles: list[Candle], bh_return: float) -> Panel:
    positions, indicators = strat.func(candles)
    res = run_backtest(candles, positions)

    pos_now = positions[-1]
    pos_prev = positions[-2] if len(positions) >= 2 else 0
    signal = signal_label(pos_prev, pos_now)
    color, icon = SIGNAL_STYLE[signal]

    lines = Text()
    lines.append(f"{icon}  {signal}\n", style=f"bold {color}")
    lines.append(f"{strat.description}\n\n", style="dim")

    # Indicatori specifici della strategia.
    if "ema_fast" in indicators:
        lines.append(f"EMA {config.EMA_FAST}:  {_fmt(indicators['ema_fast'][-1])}\n")
        lines.append(f"EMA {config.EMA_SLOW}:  {_fmt(indicators['ema_slow'][-1])}\n")
    if "rsi" in indicators:
        rsi_val = indicators["rsi"][-1]
        rsi_color = "red" if rsi_val and rsi_val > config.RSI_OVERBOUGHT else (
            "green" if rsi_val and rsi_val < config.RSI_OVERSOLD else "white")
        lines.append("RSI: ")
        lines.append(f"{_fmt(rsi_val)}\n", style=rsi_color)
    if "donchian_high" in indicators:
        lines.append(f"Max canale: {_fmt(indicators['donchian_high'][-1])}\n")
        lines.append(f"Min canale: {_fmt(indicators['donchian_low'][-1])}\n")

    stato = "DENTRO 🟢" if pos_now == 1 else "FUORI ⚪"
    lines.append(f"\nStato: {stato}\n")

    ret_color = "green" if res.return_pct >= 0 else "red"
    lines.append("Equity: ")
    lines.append(f"{config.CURRENCY}{res.final_equity:,.0f}\n", style="bold")
    lines.append("Rendimento: ")
    lines.append(f"{res.return_pct:+.2f}%\n", style=ret_color)
    vs = res.return_pct - bh_return
    vs_color = "green" if vs >= 0 else "red"
    lines.append("vs compra&tieni: ")
    lines.append(f"{vs:+.2f}%\n", style=vs_color)
    lines.append(f"Operazioni: {res.num_trades}", style="dim")

    return Panel(lines, title=f"[bold]{strat.name}[/bold]", border_style=color, width=34)


def build_view(candles: list[Candle], price: float) -> Group:
    bh = buy_and_hold(candles)
    last_close = datetime.fromtimestamp(candles[-1].ts).strftime("%d/%m %H:%M")
    header = Text()
    header.append(f"  {config.PAIR}  ", style="bold white on blue")
    header.append(f"  Prezzo live: {config.CURRENCY}{price:,.1f}", style="bold")
    header.append(f"   |   candela {config.INTERVAL}min   |   ultima chiusa: {last_close}")
    header.append(f"   |   agg.: {datetime.now().strftime('%H:%M:%S')}", style="dim")

    panels = [build_panel(s, candles, bh.return_pct) for s in STRATEGIES]
    footer = Text(
        f"\nCtrl+C per uscire · aggiornamento ogni {config.REFRESH_SECONDS}s · "
        "soldi FINTI, prezzi VERI",
        style="dim",
    )
    return Group(header, Text(""), Columns(panels, equal=True), footer)


def main() -> None:
    print("Carico i dati di mercato...", flush=True)
    with Live(refresh_per_second=4, screen=False) as live:
        while True:
            try:
                candles = fetch_candles()
                price = fetch_last_price()
                live.update(build_view(candles, price))
            except Exception as exc:  # rete instabile: mostra l'errore e riprova
                live.update(Panel(f"[red]Errore: {exc}[/red]\nRiprovo a breve...",
                                  border_style="red"))
            time.sleep(config.REFRESH_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDashboard chiusa. A presto!")
