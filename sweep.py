"""
Ottimizzazione onesta: "interroga" lo storico provando tante combinazioni di
strategie e parametri, e le ordina per risultato.

LA REGOLA ANTI-ILLUSIONE (overfitting):
Dividiamo la storia in due parti:
  - IN-SAMPLE (primo 70%): qui CERCHIAMO la combinazione migliore.
  - OUT-OF-SAMPLE (ultimo 30%): qui VERIFICHIAMO se quella combinazione regge
    su dati "mai visti". Se vince nel primo pezzo ma crolla nel secondo, era
    fortuna, non una strategia vera.

Avvio:
  python -m lab.sweep data/XBTEUR.csv            # timeframe da config (15 min)
  python -m lab.sweep data/XBTEUR.csv 60         # forza 1 ora
  python -m lab.sweep data/XBTEUR.csv 1440       # forza 1 giorno
"""

import os
import sys
from datetime import datetime
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.table import Table

from lab import config
from lab.data import Candle, load_candles_csv
from lab.portfolio import buy_and_hold, run_backtest
from lab.strategies import ema, rsi


# --- Generatori di posizioni con parametri espliciti (no config globale) ---

def pos_ema(candles, fast, slow):
    closes = [c.close for c in candles]
    f, s = ema(closes, fast), ema(closes, slow)
    return [1 if (f[i] is not None and s[i] is not None and f[i] > s[i]) else 0
            for i in range(len(candles))]


def pos_rsi(candles, period, oversold, overbought):
    vals = rsi([c.close for c in candles], period)
    out = [0] * len(candles)
    pos = 0
    for i in range(len(candles)):
        r = vals[i]
        if r is not None:
            if pos == 0 and r < oversold:
                pos = 1
            elif pos == 1 and r > overbought:
                pos = 0
        out[i] = pos
    return out


def pos_rsi_mean(candles, period, oversold, mean_period):
    closes = [c.close for c in candles]
    vals = rsi(closes, period)
    mean = ema(closes, mean_period)
    out = [0] * len(candles)
    pos = 0
    for i in range(len(candles)):
        r, m = vals[i], mean[i]
        if r is not None and m is not None:
            if pos == 0 and r < oversold:
                pos = 1
            elif pos == 1 and (closes[i] >= m or r > 70):
                pos = 0
        out[i] = pos
    return out


def pos_breakout(candles, lookback):
    out = [0] * len(candles)
    pos = 0
    for i in range(len(candles)):
        if i >= lookback:
            window = candles[i - lookback:i]
            hi = max(c.high for c in window)
            lo = min(c.low for c in window)
            if pos == 0 and candles[i].close > hi:
                pos = 1
            elif pos == 1 and candles[i].close < lo:
                pos = 0
        out[i] = pos
    return out


def build_configs(candles):
    """Restituisce una lista di (etichetta, posizioni_full) da testare."""
    cfgs = []
    # EMA crossover
    for fast, slow in [(9, 21), (9, 50), (12, 100), (20, 50), (20, 200), (50, 200)]:
        cfgs.append((f"EMA {fast}/{slow}", pos_ema(candles, fast, slow)))
    # RSI reversion
    for p, os_, ob in product([7, 14, 21], [20, 25, 30], [70, 75, 80]):
        cfgs.append((f"RSI p{p} {os_}/{ob}", pos_rsi(candles, p, os_, ob)))
    # RSI -> media
    for p, os_, mp in product([14], [25, 30, 35], [20, 50, 100, 200]):
        cfgs.append((f"RSI->media p{p} <{os_} EMA{mp}", pos_rsi_mean(candles, p, os_, mp)))
    # Breakout
    for lb in [10, 20, 55, 100]:
        cfgs.append((f"Breakout {lb}", pos_breakout(candles, lb)))
    return cfgs


def main():
    console = Console()
    path = sys.argv[1] if len(sys.argv) > 1 else "data/XBTEUR.csv"
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else config.INTERVAL

    console.print(f"\n[bold]Ottimizzazione[/bold] {path} — timeframe {interval} min")
    candles = load_candles_csv(path, interval)
    split = int(len(candles) * 0.70)
    is_c, oos_c = candles[:split], candles[split:]
    d0 = datetime.fromtimestamp(candles[0].ts).strftime("%d/%m/%Y")
    dS = datetime.fromtimestamp(candles[split].ts).strftime("%d/%m/%Y")
    dE = datetime.fromtimestamp(candles[-1].ts).strftime("%d/%m/%Y")
    console.print(f"In-sample: [cyan]{d0} → {dS}[/cyan]  |  "
                  f"Out-of-sample: [magenta]{dS} → {dE}[/magenta]")
    console.print(f"({len(candles):,} candele totali)\n")

    # Stop varianti applicate a ogni combinazione.
    stop_variants = [("no-stop", False, 0.0), ("stop5%", True, 0.05), ("stop10%", True, 0.10)]

    console.print("Calcolo le combinazioni... (puo' richiedere un minuto)")
    base_cfgs = build_configs(candles)

    results = []
    for label, pos_full in base_cfgs:
        pos_is, pos_oos = pos_full[:split], pos_full[split:]
        for slabel, son, spct in stop_variants:
            r_is = run_backtest(is_c, pos_is, stop_loss_on=son, stop_loss_pct=spct,
                                trend_filter_on=False)
            r_oos = run_backtest(oos_c, pos_oos, stop_loss_on=son, stop_loss_pct=spct,
                                 trend_filter_on=False)
            results.append((f"{label} | {slabel}", r_is, r_oos))

    # Ordiniamo per rendimento IN-SAMPLE (qui "ottimizziamo").
    results.sort(key=lambda x: x[1].return_pct, reverse=True)

    bh_is = buy_and_hold(is_c)
    bh_oos = buy_and_hold(oos_c)

    table = Table(title="Top 15 per rendimento IN-SAMPLE (e verifica OUT-OF-SAMPLE)",
                  header_style="bold")
    table.add_column("Combinazione")
    table.add_column("IN-sample", justify="right")
    table.add_column("OUT-sample", justify="right")
    table.add_column("Oper. OOS", justify="right")
    table.add_column("MaxDD OOS", justify="right")

    for label, r_is, r_oos in results[:15]:
        oos_color = "green" if r_oos.return_pct >= 0 else "red"
        table.add_row(
            label,
            f"{r_is.return_pct:+,.0f}%",
            f"[{oos_color}]{r_oos.return_pct:+,.1f}%[/{oos_color}]",
            str(r_oos.num_trades),
            f"{r_oos.max_drawdown_pct:.0f}%",
        )
    table.add_section()
    table.add_row("[yellow]Compra & tieni[/yellow]",
                  f"{bh_is.return_pct:+,.0f}%",
                  f"{bh_oos.return_pct:+,.1f}%", "1", f"{bh_oos.max_drawdown_pct:.0f}%")
    console.print(table)

    # Verdetto onesto: quante delle top 15 battono il buy&hold OUT-OF-SAMPLE?
    top = results[:15]
    beat = sum(1 for _, _, r in top if r.return_pct > bh_oos.return_pct)
    console.print(
        f"\n[bold]Verdetto:[/bold] delle 15 'migliori' sul passato, "
        f"[bold]{beat}[/bold] battono il compra&tieni sul futuro mai visto "
        f"(out-of-sample: {bh_oos.return_pct:+,.1f}%)."
    )
    console.print("[dim]Se sono poche o nessuna → era overfitting (fortuna sul passato).[/dim]\n")


if __name__ == "__main__":
    main()
