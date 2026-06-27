"""
Validazione WALK-FORWARD (passo 1 della validazione seria).

Invece di un solo taglio passato/futuro, scorriamo nel tempo:
  - per ogni anno di test, guardiamo i 3 anni PRECEDENTI ("train"),
  - scegliamo la combinazione migliore su quei 3 anni,
  - la usiamo "alla cieca" sull'anno di test,
  - confrontiamo col compra & tieni di quell'anno.

Cosi' simuliamo cosa avremmo VERAMENTE ottenuto ottimizzando di anno in anno.
Se la strategia vince in tanti anni diversi (tori e orsi) -> l'edge e' robusto.
Se vince solo in un paio di anni fortunati -> era illusione.

Avvio:
  python -m lab.walkforward data/XBTEUR.csv          # giornaliero, all-in
  python -m lab.walkforward data/XBTEUR.csv 1440 sized   # con dimensionamento rischio 1%
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.table import Table

from lab.data import load_candles_csv
from lab.portfolio import buy_and_hold, run_backtest
from lab.sweep import build_configs

STOP_VARIANTS = [("no-stop", False, 0.0), ("stop10%", True, 0.10)]
TRAIN_YEARS = 3


def main():
    console = Console()
    args = sys.argv[1:]
    sized = "sized" in args
    args = [a for a in args if a != "sized"]
    path = args[0] if len(args) > 0 else "data/XBTEUR.csv"
    interval = int(args[1]) if len(args) > 1 else 1440  # default: giornaliero

    # Con il dimensionamento del rischio serve uno stop (definisce "quanto si rischia").
    stop_variants = [("stop10%", True, 0.10)] if sized else STOP_VARIANTS
    risk_pct = 0.01

    tf = {1440: "giornaliero", 60: "1 ora", 15: "15 min"}.get(interval, f"{interval} min")
    mode = "[green]dimensionamento rischio 1%[/green]" if sized else "all-in (tutto il capitale)"
    console.print(f"\n[bold]Walk-forward[/bold] {path} — timeframe {tf} — {mode}\n"
                  f"(train {TRAIN_YEARS} anni → test 1 anno, a scorrere)\n")

    candles = load_candles_csv(path, interval)
    configs = build_configs(candles)  # [(label, posizioni_full)] calcolate una volta

    # Raggruppa gli indici delle candele per anno solare.
    years: dict[int, list[int]] = {}
    for i, c in enumerate(candles):
        years.setdefault(datetime.fromtimestamp(c.ts).year, []).append(i)
    # Tieni solo gli anni "pieni" abbastanza (evita 2013/2026 parziali su daily).
    min_candles = 200 if interval == 1440 else 2000
    full = {y for y, idx in years.items() if len(idx) >= min_candles}

    table = Table(title="Walk-forward: ottimizza sul passato, opera l'anno dopo",
                  header_style="bold")
    table.add_column("Anno test")
    table.add_column("Strategia scelta (sul train)")
    table.add_column("Strategia", justify="right")
    table.add_column("Compra&tieni", justify="right")
    table.add_column("Esito", justify="center")

    wf_equity = 1.0   # capitale composto seguendo le scelte walk-forward
    bh_equity = 1.0   # capitale composto comprando e tenendo per gli stessi anni
    wins = 0
    tested = 0

    for test_year in sorted(years):
        train_years = [test_year - k for k in range(1, TRAIN_YEARS + 1)]
        if test_year not in full or any(ty not in full for ty in train_years):
            continue

        train_idx = sorted(i for ty in train_years for i in years[ty])
        test_idx = years[test_year]
        train_candles = [candles[i] for i in train_idx]
        test_candles = [candles[i] for i in test_idx]

        # Scegli la combinazione migliore sui 3 anni di train.
        best = None  # (return_train, label, son, spct, pos_full)
        for label, pos_full in configs:
            pos_train = [pos_full[i] for i in train_idx]
            for slabel, son, spct in stop_variants:
                r = run_backtest(train_candles, pos_train, stop_loss_on=son,
                                 stop_loss_pct=spct, trend_filter_on=False,
                                 position_sizing=sized, risk_pct=risk_pct)
                if best is None or r.return_pct > best[0]:
                    best = (r.return_pct, f"{label} | {slabel}", son, spct, pos_full)

        # Applicala "alla cieca" sull'anno di test.
        _, blabel, son, spct, pos_full = best
        pos_test = [pos_full[i] for i in test_idx]
        r_test = run_backtest(test_candles, pos_test, stop_loss_on=son,
                              stop_loss_pct=spct, trend_filter_on=False,
                              position_sizing=sized, risk_pct=risk_pct)
        r_bh = buy_and_hold(test_candles)

        wf_equity *= (1 + r_test.return_pct / 100)
        bh_equity *= (1 + r_bh.return_pct / 100)
        beat = r_test.return_pct > r_bh.return_pct
        wins += beat
        tested += 1

        col = "green" if r_test.return_pct >= 0 else "red"
        table.add_row(
            str(test_year),
            blabel,
            f"[{col}]{r_test.return_pct:+.1f}%[/{col}]",
            f"{r_bh.return_pct:+.1f}%",
            "✅" if beat else "❌",
        )

    console.print(table)
    console.print(
        f"\n[bold]Risultato:[/bold] la strategia walk-forward ha battuto il compra&tieni in "
        f"[bold]{wins}/{tested}[/bold] anni.\n"
        f"Capitale composto seguendo il walk-forward: [bold]{wf_equity*10000:,.0f}€[/bold]  |  "
        f"comprando e tenendo: [bold]{bh_equity*10000:,.0f}€[/bold]  (da 10.000€)\n"
    )
    console.print("[dim]Se vince in pochi anni o perde nel composto → l'edge non e' affidabile.[/dim]\n")


if __name__ == "__main__":
    main()
