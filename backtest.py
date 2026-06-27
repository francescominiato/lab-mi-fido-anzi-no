"""
Backtest comparativo: la "tre finestre" in versione storica.

Scarica lo storico di BTC, fa girare le tre strategie sugli STESSI dati e
stampa una tabella che le mette a confronto, insieme al benchmark "compra e
tieni". Cosi' vedi a colpo d'occhio quale si e' comportata meglio (e come).

Avvio:
  python -m lab.backtest                          # dati live (ultimi ~7,5 giorni)
  python -m lab.backtest data/XBTEUR.csv          # storia da un file CSV
  python -m lab.backtest data/Q3.csv data/Q4.csv  # piu' file uniti (es. trimestri)
"""

import os
import sys
from datetime import datetime

# Permette di lanciare lo script sia con -m lab.backtest sia direttamente.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.table import Table

from lab import config
from lab.data import fetch_candles, load_candles_csv_many
from lab.portfolio import buy_and_hold, run_backtest
from lab.strategies import STRATEGIES


def main() -> None:
    console = Console()

    # Se passi uno o piu' percorsi CSV come argomenti, leggiamo la storia da li'
    # (uniti); altrimenti scarichiamo i dati live dalla CLI di Kraken.
    csv_paths = sys.argv[1:]
    if config.STOP_LOSS_ON:
        stop_txt = f"[green]stop-loss ACCESO a {config.STOP_LOSS_PCT*100:.1f}%[/green]"
    else:
        stop_txt = "[dim]stop-loss spento[/dim]"
    if config.TREND_FILTER_ON:
        trend_txt = f"[green]filtro tendenza ACCESO ({config.TREND_FILTER_PERIOD})[/green]"
    else:
        trend_txt = "[dim]filtro tendenza spento[/dim]"
    console.print(
        f"\n[bold]Backtest {config.PAIR}[/bold] — candele da {config.INTERVAL} minuti, "
        f"capitale iniziale {config.CURRENCY}{config.START_CASH:,.0f}, "
        f"fee {config.FEE_RATE*100:.2f}%\n{stop_txt} · {trend_txt}\n"
    )

    if csv_paths:
        candles = load_candles_csv_many(csv_paths)
        console.print(f"Fonte dati: [magenta]file CSV: {', '.join(csv_paths)}[/magenta]")
        fmt = "%d/%m/%Y"  # con mesi/anni di storia mostriamo anche l'anno
    else:
        candles = fetch_candles()
        console.print("Fonte dati: [magenta]live Kraken (ultimi ~7,5 giorni)[/magenta]")
        fmt = "%d/%m %H:%M"
    da = datetime.fromtimestamp(candles[0].ts).strftime(fmt)
    a = datetime.fromtimestamp(candles[-1].ts).strftime(fmt)
    console.print(
        f"Periodo analizzato: [cyan]{da}[/cyan] → [cyan]{a}[/cyan] "
        f"({len(candles):,} candele)\n"
    )

    bh = buy_and_hold(candles)

    table = Table(title="Confronto strategie", header_style="bold")
    table.add_column("Strategia")
    table.add_column("Cosa fa", style="dim")
    table.add_column("Equity finale", justify="right")
    table.add_column("Rendimento", justify="right")
    table.add_column("Operazioni", justify="right")
    table.add_column("% Vincenti", justify="right")
    table.add_column("Max perdita*", justify="right")

    for strat in STRATEGIES:
        positions, _ = strat.func(candles)
        res = run_backtest(candles, positions)
        ret_color = "green" if res.return_pct >= 0 else "red"
        table.add_row(
            f"[bold]{strat.name}[/bold]",
            strat.description,
            f"{config.CURRENCY}{res.final_equity:,.0f}",
            f"[{ret_color}]{res.return_pct:+.2f}%[/{ret_color}]",
            str(res.num_trades),
            f"{res.win_rate_pct:.0f}%",
            f"{res.max_drawdown_pct:.1f}%",
        )

    # Riga benchmark.
    bh_color = "green" if bh.return_pct >= 0 else "red"
    table.add_section()
    table.add_row(
        "[bold yellow]Compra & tieni[/bold yellow]",
        "Benchmark: comprato all'inizio, mai venduto",
        f"{config.CURRENCY}{bh.final_equity:,.0f}",
        f"[{bh_color}]{bh.return_pct:+.2f}%[/{bh_color}]",
        "1",
        "-",
        f"{bh.max_drawdown_pct:.1f}%",
    )

    console.print(table)
    console.print(
        "\n[dim]* Max perdita = peggior discesa dal massimo raggiunto (drawdown). "
        "Piu' vicina a 0 = meno stress.[/dim]"
    )
    if not csv_paths:
        console.print(
            "[dim]Nota: ~7,5 giorni di dati = utile per CAPIRE le strategie, "
            "non per trarre conclusioni definitive.[/dim]\n"
        )


if __name__ == "__main__":
    main()
