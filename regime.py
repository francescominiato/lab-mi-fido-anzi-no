"""
Classificatore di regime di mercato: rialzista / ribassista / laterale.

Idea (vedi docs/superpowers/specs/2026-06-16-classificatore-regime-design.md):
si misura la pendenza di una media lunga e la si normalizza per la volatilita'
tipica (ATR). Se la media "deriva" di molto meno di un ATR per candela, il
prezzo non va da nessuna parte -> LATERALE; altrimenti RIALZISTA o RIBASSISTA
a seconda del segno.

Il motore `classify_regimes` e' una funzione pura.
"""

import sys
from collections import Counter
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from . import config, data
from .strategies import atr, ema
from .eventstudy import (
    FLOOR_YEAR_DEFAULT,
    applica_pavimento,
    parse_duration_to_minutes,
    parse_finestre_arg,
    slice_periods,
)

REGIMI = ("rialzista", "ribassista", "laterale")

console = Console()


def classify_regimes(
    candles,
    ma_period: int = config.REGIME_MA_PERIOD,
    atr_period: int = config.REGIME_ATR_PERIOD,
    slope_lookback: int = config.REGIME_SLOPE_LOOKBACK,
    flat_threshold: float = config.REGIME_FLAT_THRESHOLD,
) -> list[str | None]:
    """
    Restituisce una lista lunga quanto `candles`: per ogni candela una di
    'rialzista' / 'ribassista' / 'laterale', oppure None durante il
    riscaldamento (media/ATR/pendenza non ancora calcolabili).

    Il riscaldamento NON dura solo `slope_lookback` candele: serve che anche la
    media sia gia' calcolabile `slope_lookback` candele fa. La prima etichetta
    valida arriva all'incirca all'indice `ma_period - 1 + slope_lookback`
    (con i default 20+20 -> circa 39 candele).
    """
    closes = [c.close for c in candles]
    ma = ema(closes, ma_period)
    atr_vals = atr(candles, atr_period)
    out = [None] * len(candles)
    for i in range(len(candles)):
        if i < slope_lookback:
            continue
        m_now = ma[i]
        m_prev = ma[i - slope_lookback]
        a = atr_vals[i]
        if m_now is None or m_prev is None or a is None:
            continue
        if m_prev == 0 or closes[i] == 0:
            continue
        atr_pct = a / closes[i]
        if atr_pct == 0:
            continue
        slope = (m_now - m_prev) / m_prev          # variazione % della media su L candele
        forza = (slope / slope_lookback) / atr_pct  # drift per candela, in unita' di ATR
        if abs(forza) < flat_threshold:
            out[i] = "laterale"
        elif forza > 0:
            out[i] = "rialzista"
        else:
            out[i] = "ribassista"
    return out


def distribuzione(labels) -> dict:
    """
    Da una lista di etichette (con eventuali None) calcola le percentuali per
    regime. I None sono esclusi. Ritorna {regime: pct, ..., 'n': conteggio_valide}.
    """
    validi = [x for x in labels if x is not None]
    n = len(validi)
    conta = Counter(validi)
    out = {r: (100.0 * conta.get(r, 0) / n if n else 0.0) for r in REGIMI}
    out["n"] = n
    return out


def per_anno(candles, labels) -> list:
    """
    Raggruppa (candela, etichetta) per anno solare e calcola la distribuzione
    di ciascun anno. Ritorna una lista ordinata di (anno, dict_distribuzione).
    """
    per: dict[int, list] = {}
    for c, lab in zip(candles, labels):
        anno = datetime.fromtimestamp(c.ts, tz=timezone.utc).year
        per.setdefault(anno, []).append(lab)
    return [(anno, distribuzione(per[anno])) for anno in sorted(per)]


def distrib_per_slice(candles, labels, mode, params) -> list:
    """
    Applica la stessa logica di slicing di eventstudy (no/split/finestre) e
    calcola la distribuzione dei regimi per ogni fetta. Ritorna lista di
    (nome_fetta, dict_distribuzione). Le etichette sono associate alle candele
    per timestamp (il motore e' gia' stato calcolato sull'intera serie).
    """
    label_by_ts = {c.ts: lab for c, lab in zip(candles, labels)}
    out = []
    for nome, sub in slice_periods(candles, mode, params):
        sub_labels = [label_by_ts.get(c.ts) for c in sub]
        out.append((nome, distribuzione(sub_labels)))
    return out



def _riga_pct(dist) -> tuple:
    return (
        f"{dist['rialzista']:.1f}%",
        f"{dist['ribassista']:.1f}%",
        f"{dist['laterale']:.1f}%",
        str(dist["n"]),
    )


def render_report(title, complessiva, regime_attuale, righe_anno, righe_slice):
    console.print(f"\n[bold]{title}[/bold]\n")

    tab = Table(title="Ripartizione complessiva")
    tab.add_column("Rialzista", justify="right")
    tab.add_column("Ribassista", justify="right")
    tab.add_column("Laterale", justify="right")
    tab.add_column("Candele valide", justify="right")
    tab.add_row(*_riga_pct(complessiva))
    console.print(tab)
    console.print(f"Regime attuale (ultima candela): [bold]{regime_attuale}[/bold]\n")

    tab_anno = Table(title="Ripartizione per anno")
    tab_anno.add_column("Anno")
    tab_anno.add_column("Rialzista", justify="right")
    tab_anno.add_column("Ribassista", justify="right")
    tab_anno.add_column("Laterale", justify="right")
    tab_anno.add_column("Candele", justify="right")
    for anno, dist in righe_anno:
        tab_anno.add_row(str(anno), *_riga_pct(dist))
    console.print(tab_anno)

    if righe_slice is not None:
        tab_s = Table(title="Verifica di stabilita' (distribuzione per fetta)")
        tab_s.add_column("Fetta")
        tab_s.add_column("Rialzista", justify="right")
        tab_s.add_column("Ribassista", justify="right")
        tab_s.add_column("Laterale", justify="right")
        tab_s.add_column("Candele", justify="right")
        for nome, dist in righe_slice:
            tab_s.add_row(nome, *_riga_pct(dist))
        console.print(tab_s)


def _parse_cli(argv):
    """CSV INTERVAL [--da ANNO] [--split N | --finestre W:S]"""
    path = argv[0]
    interval = parse_duration_to_minutes(argv[1])
    floor_year = FLOOR_YEAR_DEFAULT
    mode, params = "no", {}
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == "--da":
            floor_year = int(argv[i + 1]); i += 2
        elif a == "--split":
            mode = "split"; params = {"split_pct": int(argv[i + 1])}; i += 2
        elif a == "--finestre":
            w, s = parse_finestre_arg(argv[i + 1])
            mode = "finestre"; params = {"width_years": w, "step_years": s}; i += 2
        else:
            raise ValueError(f"argomento sconosciuto: {a}")
    return path, interval, floor_year, mode, params


def _ask(prompt, default):
    val = input(f"{prompt} [{default}]: ").strip()
    return val or default


def _wizard():
    console.print("[bold]Classificatore di regime[/bold] — premi Invio per i default\n")
    path = _ask("File CSV", "data/XBTEUR.csv")
    interval = parse_duration_to_minutes(_ask("Timeframe (es. 1g, 1h, 15min)", "1g"))
    floor_year = int(_ask(f"Da quale anno (min consigliato {FLOOR_YEAR_DEFAULT})",
                          str(FLOOR_YEAR_DEFAULT)))
    stab = _ask("Stabilita': no / split N / finestre W:S", "no").split()
    mode, params = "no", {}
    try:
        if stab and stab[0] == "split":
            mode = "split"; params = {"split_pct": int(stab[1])}
        elif stab and stab[0] == "finestre":
            w, s = parse_finestre_arg(stab[1])
            mode = "finestre"; params = {"width_years": w, "step_years": s}
    except (IndexError, ValueError):
        raise ValueError("stabilita' malformata: usa 'split 70' oppure 'finestre 3a:1a'")
    return path, interval, floor_year, mode, params


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        cfg = _parse_cli(argv) if argv else _wizard()
    except (ValueError, IndexError) as e:
        console.print(f"[red]Argomenti non validi: {e}[/red]")
        console.print("Uso: python -m lab.regime CSV INTERVAL "
                      "[--da ANNO] [--split N | --finestre W:S]")
        console.print("Esempio: python -m lab.regime data/XBTEUR.csv 1g "
                      "--split 70   (N = percentuale in-sample, es. 70)")
        return 1
    path, interval, floor_year, mode, params = cfg
    try:
        candles = data.load_candles_csv(path, interval)
    except (OSError, RuntimeError) as e:
        console.print(f"[red]Errore nel caricare i dati: {e}[/red]")
        return 1
    candles = applica_pavimento(candles, floor_year)
    if not candles:
        console.print(f"[red]Nessun dato dal {floor_year} in poi.[/red]")
        return 1
    if floor_year < FLOOR_YEAR_DEFAULT:
        console.print(f"[yellow]⚠ stai includendo anni a liquidita' sottile "
                      f"(pre-{FLOOR_YEAR_DEFAULT}): possibili falsi pattern[/yellow]")

    labels = classify_regimes(candles)
    complessiva = distribuzione(labels)
    attuale = next((x for x in reversed(labels) if x is not None), "n/d")
    righe_anno = per_anno(candles, labels)
    righe_slice = None if mode == "no" else distrib_per_slice(candles, labels, mode, params)

    title = (f"Regimi: {path}  |  candela {interval}min  |  dal {floor_year}  |  "
             f"MA{config.REGIME_MA_PERIOD}/ATR{config.REGIME_ATR_PERIOD}/"
             f"L{config.REGIME_SLOPE_LOOKBACK}/soglia {config.REGIME_FLAT_THRESHOLD}")
    render_report(title, complessiva, attuale, righe_anno, righe_slice)
    return 0


if __name__ == "__main__":
    sys.exit(main())
