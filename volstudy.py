"""
Studio "VOLUME -> POP": dopo una candela a VOLUME IMPORTANTE, quanto spesso e in
quanti minuti il prezzo sale di almeno X%?

Analisi DESCRITTIVA (non un backtest di strategia), nello spirito di lab.eventstudy:
ogni numero degli "eventi" (candele a volume alto) e' sempre confrontato con una
BASELINE (un momento qualsiasi), cosi' non ci raccontiamo storie. Verifica di
stabilita' opzionale (--split / --finestre).

Perche': il "volume importante" e' un candidato SEGNALE d'ingresso. Qui misuriamo
se, dopo un'ondata di volume, il prezzo raggiunge un target rialzista PIU' spesso
o PIU' in fretta del normale. Se non lo fa, il volume non e' un edge (coerente con
DISTILLATO.md: "volume = informativo ma NON predittivo ne' stabile").

Dati: legge un CSV di candele (es. data/XBTEUR.csv.c1.csv, 1-min) e le AGGREGA al
timeframe scelto in streaming (poca memoria). Il volume e' solo della borsa del
file (Kraken), da leggere in RELATIVO (rapporto col volume medio recente).

Uso:
  python -m lab.volstudy CSV TF VOLMULT TARGETS ORIZZONTE [opzioni]
    CSV       file candele (default consigliato: data/XBTEUR.csv.c1.csv)
    TF        minuti per candela (es. 3)
    VOLMULT   "volume importante" = volume >= VOLMULT x media dei precedenti (es. 3)
    TARGETS   uno o piu' target % separati da virgola (es. 1  oppure  1,2)
    ORIZZONTE tempo massimo per raggiungere il target (es. 2h, 90min)
  Opzioni: [--da ANNO] [--ore I-F] [--lookback N] [--split N | --finestre W:S]

Esempi:
  python -m lab.volstudy data/XBTEUR.csv.c1.csv 3 3 1,2 2h --da 2017
  python -m lab.volstudy data/XBTEUR.csv.c1.csv 3 3 1 2h --ore 12-16 --split 70
"""

import datetime
import random
import statistics
import sys

from rich.console import Console
from rich.table import Table

from .eventstudy import (
    ora_utc, in_fascia, parse_ore_arg, parse_duration_to_minutes,
    parse_finestre_arg, FLOOR_YEAR_DEFAULT, BASELINE_SEED,
    MIN_EVENTI_AFFIDABILE, YEAR_SECONDS, _fmt_ts, _human_minutes,
)

console = Console()

VOLUME_LOOKBACK = 20
BASELINE_SIZE = 3000

# Indici nella tupla candela: (ts, open, high, low, close, volume)
TS, O, HI, LO, C, V = 0, 1, 2, 3, 4, 5


def load_tf(path, tf_min):
    """Streamma un CSV di candele (ts,o,h,l,c,v) e aggrega a candele da tf_min minuti.
    Memoria contenuta: legge riga per riga, accumula in secchielli da tf_min."""
    path = path.replace("~", __import__("os").path.expanduser("~"))
    size = tf_min * 60
    buckets = {}
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            p = line.split(",")
            try:
                ts = int(float(p[0]))
                o = float(p[1]); hi = float(p[2]); lo = float(p[3]); c = float(p[4]); v = float(p[5])
            except (ValueError, IndexError):
                continue
            b = ts - (ts % size)
            e = buckets.get(b)
            if e is None:
                # [min_ts, open, max_ts, close, high, low, vol]
                buckets[b] = [ts, o, ts, c, hi, lo, v]
            else:
                if ts <= e[0]:
                    e[0] = ts; e[1] = o
                if ts >= e[2]:
                    e[2] = ts; e[3] = c
                if hi > e[4]:
                    e[4] = hi
                if lo < e[5]:
                    e[5] = lo
                e[6] += v
    return [(b, e[1], e[4], e[5], e[3], e[6]) for b, e in sorted(buckets.items())]


def applica_pavimento(candles, anno):
    t0 = datetime.datetime(anno, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    return [c for c in candles if c[TS] >= t0]


def vol_ratio(candles, i, lookback):
    """Volume della candela i diviso la media dei `lookback` volumi precedenti."""
    if i < lookback:
        return None
    media = sum(candles[j][V] for j in range(i - lookback, i)) / lookback
    if media <= 0:
        return None
    return candles[i][V] / media


def first_pass_up(candles, i, target_pct, horizon_sec):
    """Minuti dal trigger i (entrata = sua chiusura) al primo tocco di +target_pct
    sul massimo, entro horizon_sec. None se non lo raggiunge in tempo."""
    ref = candles[i][C]
    target = ref * (1 + target_pct / 100.0)
    t0 = candles[i][TS]
    n = len(candles)
    j = i + 1
    while j < n and candles[j][TS] - t0 <= horizon_sec:
        if candles[j][HI] >= target:
            return (candles[j][TS] - t0) / 60.0
        j += 1
    return None


def reach_down(candles, i, target_pct, horizon_sec):
    """Vero se entro horizon_sec il prezzo SCENDE di -target_pct (sul minimo)."""
    ref = candles[i][C]
    stop = ref * (1 - target_pct / 100.0)
    t0 = candles[i][TS]
    n = len(candles)
    j = i + 1
    while j < n and candles[j][TS] - t0 <= horizon_sec:
        if candles[j][LO] <= stop:
            return True
        j += 1
    return False


def _has_room(candles, i, horizon_sec):
    """Vero se dalla candela i c'e' abbastanza storia avanti per coprire l'orizzonte."""
    return candles[-1][TS] - candles[i][TS] >= horizon_sec


def measure_group(candles, idx, targets, horizon_sec):
    """Per ogni target: % che lo raggiunge in salita, minuti (mediana/media) di chi
    ci arriva, e % che invece SCENDE di pari entita' nell'orizzonte (specchio)."""
    out = {"n": len(idx)}
    for x in targets:
        ups = [m for i in idx if (m := first_pass_up(candles, i, x, horizon_sec)) is not None]
        downs = sum(1 for i in idx if reach_down(candles, i, x, horizon_sec))
        n = len(idx)
        out[x] = {
            "reach_pct": (len(ups) / n * 100.0) if n else 0.0,
            "med": statistics.median(ups) if ups else None,
            "mean": statistics.mean(ups) if ups else None,
            "down_pct": (downs / n * 100.0) if n else 0.0,
        }
    return out


def analyze_slice(candles, volmult, targets, horizon_sec, lookback, ore):
    """Trigger = candele a volume_ratio >= volmult (con orizzonte coperto e nella
    fascia oraria scelta). Baseline = campione casuale di candele qualsiasi."""
    valid = [i for i in range(lookback, len(candles))
             if _has_room(candles, i, horizon_sec)
             and (ore is None or in_fascia(ora_utc(candles[i][TS]), *ore))]
    trig = [i for i in valid if (r := vol_ratio(candles, i, lookback)) is not None and r >= volmult]
    # baseline: campione casuale e ripetibile fra tutte le candele valide
    if len(valid) > BASELINE_SIZE:
        rng = random.Random(BASELINE_SEED)
        base = sorted(rng.sample(valid, BASELINE_SIZE))
    else:
        base = valid
    return {
        "trigger": measure_group(candles, trig, targets, horizon_sec),
        "baseline": measure_group(candles, base, targets, horizon_sec),
    }


def slice_periods(candles, mode, params):
    if mode == "no":
        return [("Tutta la storia", candles)]
    if mode == "split":
        x = params["split"]
        cut = int(len(candles) * x / 100)
        return [(f"In-sample (primo {x}%)", candles[:cut]),
                (f"Out-of-sample (ultimo {100 - x}%)", candles[cut:])]
    if mode == "finestre":
        width = int(params["w"] * YEAR_SECONDS)
        step = int(params["s"] * YEAR_SECONDS)
        first_ts, last_ts = candles[0][TS], candles[-1][TS]
        out = []
        w_start = first_ts
        while w_start <= last_ts:
            sub = [c for c in candles if w_start <= c[TS] < w_start + width]
            if sub:
                out.append((f"{_fmt_ts(w_start)} -> {_fmt_ts(w_start + width)}", sub))
            w_start += step
        return out
    raise ValueError(f"modalita' stabilita' sconosciuta: {mode}")


def _mins(m):
    return f"{m:.0f}m" if m is not None else "-"


def render(title, slices_results, targets, horizon_min):
    console.print(f"\n[bold]{title}[/bold]")
    hh = _human_minutes(horizon_min)
    for label, res in slices_results:
        trig, base = res["trigger"], res["baseline"]
        head = f"{label} — trigger: {trig['n']} | baseline: {base['n']}"
        if trig["n"] < MIN_EVENTI_AFFIDABILE:
            head += "  [yellow]⚠ pochi trigger, poco affidabile[/yellow]"
        console.print(f"\n[bold cyan]{head}[/bold cyan]")
        if trig["n"] == 0:
            console.print("[red]nessun trigger con questi parametri[/red]")
            continue
        table = Table(show_header=True, header_style="bold")
        table.add_column("Target")
        table.add_column(f"Trigger: sale entro {hh}", justify="right")
        table.add_column("Baseline: sale", justify="right")
        table.add_column("Mediana min (trig)", justify="right")
        table.add_column("Media min (trig)", justify="right")
        table.add_column("Scende -X (trig/base)", justify="right")
        for x in targets:
            t, b = trig[x], base[x]
            table.add_row(
                f"+{x:g}%",
                f"{t['reach_pct']:.1f}%",
                f"{b['reach_pct']:.1f}%",
                _mins(t["med"]),
                _mins(t["mean"]),
                f"{t['down_pct']:.0f}% / {b['down_pct']:.0f}%",
            )
        console.print(table)


def _parse_cli(argv):
    path = argv[0]
    tf = int(argv[1])
    volmult = float(argv[2])
    targets = [float(s) for s in argv[3].split(",") if s.strip()]
    horizon_min = parse_duration_to_minutes(argv[4])
    floor_year = FLOOR_YEAR_DEFAULT
    ore = None
    lookback = VOLUME_LOOKBACK
    mode, params = "no", {}
    rest = argv[5:]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--da":
            floor_year = int(rest[i + 1]); i += 1
        elif a == "--ore":
            ore = parse_ore_arg(rest[i + 1]); i += 1
        elif a == "--lookback":
            lookback = int(rest[i + 1]); i += 1
        elif a == "--split":
            mode = "split"; params["split"] = int(rest[i + 1]); i += 1
        elif a == "--finestre":
            mode = "finestre"; params["w"], params["s"] = parse_finestre_arg(rest[i + 1]); i += 1
        else:
            raise ValueError(f"argomento non riconosciuto: {a}")
        i += 1
    return path, tf, volmult, targets, horizon_min, floor_year, ore, lookback, mode, params


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        console.print(__doc__)
        return 1
    try:
        (path, tf, volmult, targets, horizon_min, floor_year,
         ore, lookback, mode, params) = _parse_cli(argv)
    except (ValueError, IndexError) as e:
        console.print(f"[red]Argomenti non validi: {e}[/red]")
        console.print(__doc__)
        return 1

    console.print(f"[dim]Carico e aggrego a {tf}min da {path} ...[/dim]")
    candles = load_tf(path, tf)
    candles = applica_pavimento(candles, floor_year)
    if len(candles) < lookback + 10:
        console.print("[red]Troppe poche candele dopo il pavimento.[/red]")
        return 1
    if floor_year < FLOOR_YEAR_DEFAULT:
        console.print(f"[yellow]⚠ includi anni a liquidita' sottile (pre-{FLOOR_YEAR_DEFAULT}): possibili falsi pattern[/yellow]")

    horizon_sec = horizon_min * 60
    title = (f"Volume>={volmult:g}x media({lookback}) -> sale di X% | candele {tf}min | "
             f"orizzonte {_human_minutes(horizon_min)} | dal {floor_year}")
    if ore is not None:
        title += f" | ore {ore[0]}-{ore[1]} UTC"

    slices = slice_periods(candles, mode, params)
    results = [(label, analyze_slice(sub, volmult, targets, horizon_sec, lookback, ore))
               for label, sub in slices]
    render(title, results, targets, horizon_min)
    console.print("\n[dim]Promemoria: 'sale entro' va confrontato con la colonna Baseline; "
                  "se i due numeri sono simili, il volume non aggiunge informazione. "
                  "Guarda anche 'Scende -X': se sale E scende piu' della baseline, "
                  "il volume = volatilita', non direzione. Costo giro ~0,52%: "
                  "un target piu' piccolo di così, netto, è in perdita.[/dim]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
