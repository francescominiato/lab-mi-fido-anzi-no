"""
Studio degli eventi: cosa fa il prezzo DOPO una candela che si muove oltre una soglia.

Analisi descrittiva (NON un backtest di strategia). Trova ogni candela che supera una
soglia di variazione % e misura il comportamento del prezzo nella finestra successiva,
confrontandolo con una baseline. Verifica opzionale di stabilità nel tempo.

Spec: docs/superpowers/specs/2026-06-14-eventstudy-design.md
"""

import datetime
import random
import statistics
import sys

from rich.console import Console
from rich.table import Table

from . import data
from .data import Candle

console = Console()

TIMEFRAMES = {"15min": 15, "1h": 60, "4h": 240, "1g": 1440}
YEAR_SECONDS = int(365.25 * 24 * 3600)
MIN_EVENTI_AFFIDABILE = 30
BASELINE_DEFAULT_SIZE = 2000
BASELINE_SEED = 42
FLOOR_YEAR_DEFAULT = 2017
VOLUME_LOOKBACK = 20


def candle_change_pct(c: Candle) -> float:
    """Variazione % di una candela: dall'apertura alla chiusura."""
    return (c.close - c.open) / c.open * 100.0


def applica_pavimento(candles, anno):
    """Tiene solo le candele dal 1° gennaio di `anno` in poi (taglia gli anni illiquidi iniziali)."""
    soglia_ts = datetime.datetime(anno, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    return [c for c in candles if c.ts >= soglia_ts]


def ora_utc(ts):
    """Ora UTC (0-23) di un timestamp."""
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).hour


def in_fascia(ora, inizio, fine):
    """Vero se `ora` è nella fascia [inizio, fine) UTC. Se inizio>fine gira a mezzanotte; se uguali, tutto il giorno."""
    if inizio == fine:
        return True
    if inizio < fine:
        return inizio <= ora < fine
    return ora >= inizio or ora < fine


def parse_ore_arg(s):
    """'0-7'->(0,7); stringa vuota->None; valida 0<=inizio<=23, 0<=fine<=24."""
    s = s.strip()
    if not s:
        return None
    a, b = s.split("-")
    inizio, fine = int(a), int(b)
    if not (0 <= inizio <= 23 and 0 <= fine <= 24):
        raise ValueError("Fascia oraria non valida: usa INIZIO-FINE con ore 0-23")
    return (inizio, fine)


def volume_ratio(candles, t0, lookback=VOLUME_LOOKBACK):
    """Volume della candela t0 diviso la media dei `lookback` volumi precedenti. None se non calcolabile."""
    if t0 < lookback:
        return None
    media = sum(candles[j].volume for j in range(t0 - lookback, t0)) / lookback
    if media <= 0:
        return None
    return candles[t0].volume / media


def split_eventi_per_volume(candles, ev_idx, lookback=VOLUME_LOOKBACK):
    """Divide gli indici evento in (alto, basso) per mediana del volume_ratio. Esclude i ratio None."""
    coppie = [(i, r) for i in ev_idx if (r := volume_ratio(candles, i, lookback)) is not None]
    if not coppie:
        return [], []
    med = statistics.median([r for _, r in coppie])
    alto = [i for i, r in coppie if r >= med]
    basso = [i for i, r in coppie if r < med]
    return alto, basso


def find_events(candles, threshold):
    """Indici delle candele-evento. Soglia <0 -> crolli (<=); soglia >0 -> spike (>=)."""
    if threshold < 0:
        return [i for i, c in enumerate(candles) if candle_change_pct(c) <= threshold]
    return [i for i, c in enumerate(candles) if candle_change_pct(c) >= threshold]


def _tappe(N):
    """Tre tappe automatiche dentro la finestra: a 1/4, 1/2 e fine (almeno 1 candela)."""
    return sorted({max(1, round(N * f)) for f in (0.25, 0.5, 1.0)})


def measure_window(candles, t0, N):
    """Misure rispetto alla chiusura di t0, nelle N candele successive. None se sfora i dati."""
    if t0 + N >= len(candles):
        return None
    base = candles[t0].close
    tappe = _tappe(N)
    rets = {k: (candles[t0 + k].close - base) / base * 100.0 for k in tappe}
    highs = [candles[t0 + j].high for j in range(1, N + 1)]
    lows = [candles[t0 + j].low for j in range(1, N + 1)]
    return {
        "rets": rets,
        "mfe": (max(highs) - base) / base * 100.0,
        "mae": (min(lows) - base) / base * 100.0,
        "final_up": candles[t0 + N].close > base,
        "tappe": tappe,
    }


def aggregate(measures):
    """Media/mediana dei rendimenti per tappa, MFE/MAE, e % di eventi chiusi in positivo."""
    if not measures:
        return None
    tappe = measures[0]["tappe"]
    ret = {}
    for k in tappe:
        vals = [m["rets"][k] for m in measures]
        ret[k] = {"media": statistics.mean(vals), "mediana": statistics.median(vals)}
    mfes = [m["mfe"] for m in measures]
    maes = [m["mae"] for m in measures]
    ups = sum(1 for m in measures if m["final_up"])
    n = len(measures)
    return {
        "n": n,
        "tappe": tappe,
        "ret": ret,
        "mfe": {"media": statistics.mean(mfes), "mediana": statistics.median(mfes)},
        "mae": {"media": statistics.mean(maes), "mediana": statistics.median(maes)},
        "prob_up": ups / n * 100.0,
    }


def build_baseline_indices(candles, N, mode, n_events, seed=BASELINE_SEED, ore=None):
    """Indici t0 per la baseline. 'tutte' = ogni candela valida; 'campione' = casuale e ripetibile.
    Se `ore` è una fascia (inizio, fine), considera solo le candele in quella fascia UTC."""
    valid = [i for i in range(max(0, len(candles) - N))
             if ore is None or in_fascia(ora_utc(candles[i].ts), *ore)]
    if mode == "tutte" or not valid:
        return valid
    # dimensione del campione: BASELINE_DEFAULT_SIZE di default, ma almeno quanti sono gli eventi
    size = min(BASELINE_DEFAULT_SIZE, len(valid))
    if n_events > size:
        size = min(n_events, len(valid))
    if size >= len(valid):
        return valid
    rng = random.Random(seed)
    return sorted(rng.sample(valid, size))


def analyze_slice(candles, threshold, N, baseline_mode, ore=None):
    """Esegue trova-eventi + misura + aggrega + baseline su una fetta di candele.
    Se `ore` è una fascia (inizio, fine), tiene solo gli eventi/baseline in quella fascia UTC."""
    ev_idx = find_events(candles, threshold)
    if ore is not None:
        ev_idx = [i for i in ev_idx if in_fascia(ora_utc(candles[i].ts), *ore)]
    # scarta gli eventi/candele troppo vicini alla fine dei dati (measure_window -> None)
    ev_measures = [m for i in ev_idx if (m := measure_window(candles, i, N)) is not None]
    bl_idx = build_baseline_indices(candles, N, baseline_mode, len(ev_measures), ore=ore)
    bl_measures = [m for i in bl_idx if (m := measure_window(candles, i, N)) is not None]
    return {
        "events": aggregate(ev_measures),
        "baseline": aggregate(bl_measures),
        "n_events": len(ev_measures),
    }


def analyze_slice_volume(candles, threshold, N, baseline_mode, lookback=VOLUME_LOOKBACK, ore=None):
    """Come analyze_slice ma sdoppia gli eventi per volume (alto/basso) via mediana del volume_ratio."""
    ev_idx = [i for i in find_events(candles, threshold)
              if measure_window(candles, i, N) is not None]
    if ore is not None:
        ev_idx = [i for i in ev_idx if in_fascia(ora_utc(candles[i].ts), *ore)]
    alto_idx, basso_idx = split_eventi_per_volume(candles, ev_idx, lookback)

    def agg(idx):
        return aggregate([measure_window(candles, i, N) for i in idx])

    bl_idx = build_baseline_indices(candles, N, baseline_mode, len(ev_idx), ore=ore)
    bl_measures = [m for i in bl_idx if (m := measure_window(candles, i, N)) is not None]
    return {
        "alto": agg(alto_idx),
        "basso": agg(basso_idx),
        "baseline": aggregate(bl_measures),
        "n_alto": len(alto_idx),
        "n_basso": len(basso_idx),
    }


def _fmt_ts(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m")


def slice_periods(candles, mode, params):
    """Divide le candele in fette temporali per la verifica di stabilità."""
    if mode == "no":
        return [("Tutta la storia", candles)]
    if mode == "split":
        x = params["split_pct"]
        cut = int(len(candles) * x / 100)
        return [
            (f"In-sample (primo {x}%)", candles[:cut]),
            (f"Out-of-sample (ultimo {100 - x}%)", candles[cut:]),
        ]
    if mode == "finestre":
        width = int(params["width_years"] * YEAR_SECONDS)
        step = int(params["step_years"] * YEAR_SECONDS)
        if step <= 0:
            raise ValueError("Il passo delle finestre deve essere > 0 anni.")
        first_ts, last_ts = candles[0].ts, candles[-1].ts
        out = []
        w_start = first_ts
        while w_start <= last_ts:
            w_end = w_start + width
            sub = [c for c in candles if w_start <= c.ts < w_end]
            if sub:
                out.append((f"{_fmt_ts(w_start)} → {_fmt_ts(w_end)}", sub))
            w_start += step
        return out
    raise ValueError(f"Modalità stabilità sconosciuta: {mode}")


def parse_duration_to_minutes(s):
    """'4h'->240, '30min'->30, '1g'->1440, '15'->15 (minuti)."""
    s = s.strip().lower()
    if s.endswith("min"):
        return int(s[:-3])
    if s.endswith("h"):
        return int(s[:-1]) * 60
    if s.endswith("g"):
        return int(s[:-1]) * 1440
    return int(s)


def _years(s):
    """'1a'->1.0, '3'->3.0 (anni)."""
    return float(s.strip().lower().rstrip("a"))


def parse_finestre_arg(s):
    """'AMPIEZZA:PASSO' in anni, es. '1a:1a' -> (1.0, 1.0)."""
    w, st = s.split(":")
    return _years(w), _years(st)


def _human_minutes(m):
    if m % 1440 == 0:
        return f"{m // 1440}g"
    if m % 60 == 0:
        return f"{m // 60}h"
    return f"{m}min"


def tappe_labels(tappe, interval_min):
    """Converte le tappe (numero di candele) in etichette di tempo (1h, 2h, ...)."""
    return [_human_minutes(k * interval_min) for k in tappe]


def _fmt_pct(x):
    return f"{x:+.2f}%"


def render_report(title, slices_results, tappe_labels):
    """Stampa il report con rich: una sezione per fetta, tabella Eventi vs Baseline."""
    console.print(f"\n[bold]{title}[/bold]")
    for label, res in slices_results:
        ev, bl, n = res["events"], res["baseline"], res["n_events"]
        head = f"{label} — {n} eventi"
        if n < MIN_EVENTI_AFFIDABILE:
            head += "  [yellow]⚠ campione piccolo, poco affidabile[/yellow]"
        console.print(f"\n[bold cyan]{head}[/bold cyan]")
        if ev is None:
            console.print("[red]nessun evento con questi parametri[/red]")
            continue
        table = Table(show_header=True, header_style="bold")
        table.add_column("Metrica")
        table.add_column("Eventi", justify="right")
        table.add_column("Baseline", justify="right")
        for k, lab in zip(ev["tappe"], tappe_labels):
            table.add_row(f"Rendimento medio @{lab}",
                          _fmt_pct(ev["ret"][k]["media"]),
                          _fmt_pct(bl["ret"][k]["media"]) if bl else "-")
            table.add_row(f"Rendimento mediano @{lab}",
                          _fmt_pct(ev["ret"][k]["mediana"]),
                          _fmt_pct(bl["ret"][k]["mediana"]) if bl else "-")
        table.add_row("Prob. prezzo sopra la chiusura a fine finestra",
                      f"{ev['prob_up']:.1f}%",
                      f"{bl['prob_up']:.1f}%" if bl else "-")
        table.add_row("MFE medio (max recupero)",
                      _fmt_pct(ev["mfe"]["media"]),
                      _fmt_pct(bl["mfe"]["media"]) if bl else "-")
        table.add_row("MAE medio (max calo)",
                      _fmt_pct(ev["mae"]["media"]),
                      _fmt_pct(bl["mae"]["media"]) if bl else "-")
        console.print(table)


def _vcell(agg, getter):
    """Formatta una cella per un gruppo; '-' se il gruppo è vuoto (agg None)."""
    return getter(agg) if agg is not None else "-"


def render_report_volume(title, slices_results, tappe_labels):
    """Report a 3 colonne dati: Vol-alto | Vol-basso | Baseline."""
    console.print(f"\n[bold]{title}[/bold]")
    for label, res in slices_results:
        alto, basso, bl = res["alto"], res["basso"], res["baseline"]
        na, nb = res["n_alto"], res["n_basso"]
        head = f"{label} — vol-alto: {na} | vol-basso: {nb}"
        if min(na, nb) < MIN_EVENTI_AFFIDABILE:
            head += "  [yellow]⚠ gruppo piccolo, poco affidabile[/yellow]"
        console.print(f"\n[bold cyan]{head}[/bold cyan]")
        ref = alto if alto is not None else basso
        if ref is None:
            console.print("[red]troppi pochi eventi per lo split volume[/red]")
            continue
        table = Table(show_header=True, header_style="bold")
        table.add_column("Metrica")
        table.add_column("Vol-alto", justify="right")
        table.add_column("Vol-basso", justify="right")
        table.add_column("Baseline", justify="right")
        for k, lab in zip(ref["tappe"], tappe_labels):
            table.add_row(f"Rendimento medio @{lab}",
                          _vcell(alto, lambda a: _fmt_pct(a["ret"][k]["media"])),
                          _vcell(basso, lambda a: _fmt_pct(a["ret"][k]["media"])),
                          _vcell(bl, lambda a: _fmt_pct(a["ret"][k]["media"])))
            table.add_row(f"Rendimento mediano @{lab}",
                          _vcell(alto, lambda a: _fmt_pct(a["ret"][k]["mediana"])),
                          _vcell(basso, lambda a: _fmt_pct(a["ret"][k]["mediana"])),
                          _vcell(bl, lambda a: _fmt_pct(a["ret"][k]["mediana"])))
        table.add_row("Prob. prezzo sopra la chiusura a fine finestra",
                      _vcell(alto, lambda a: f"{a['prob_up']:.1f}%"),
                      _vcell(basso, lambda a: f"{a['prob_up']:.1f}%"),
                      _vcell(bl, lambda a: f"{a['prob_up']:.1f}%"))
        table.add_row("MFE medio (max recupero)",
                      _vcell(alto, lambda a: _fmt_pct(a["mfe"]["media"])),
                      _vcell(basso, lambda a: _fmt_pct(a["mfe"]["media"])),
                      _vcell(bl, lambda a: _fmt_pct(a["mfe"]["media"])))
        table.add_row("MAE medio (max calo)",
                      _vcell(alto, lambda a: _fmt_pct(a["mae"]["media"])),
                      _vcell(basso, lambda a: _fmt_pct(a["mae"]["media"])),
                      _vcell(bl, lambda a: _fmt_pct(a["mae"]["media"])))
        console.print(table)


def _parse_cli(argv):
    """argv: PATH INTERVAL SOGLIA FINESTRA [campione|tutte] [--split N | --finestre W:S] [--da ANNO] [--volume] [--ore I-F]."""
    path = argv[0]
    interval = int(argv[1])
    threshold = float(argv[2])
    window = argv[3]
    baseline = "campione"
    mode, params = "no", {}
    floor_year = FLOOR_YEAR_DEFAULT
    volume_on = False
    ore = None
    rest = argv[4:]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("campione", "tutte"):
            baseline = a
        elif a == "--split":
            mode = "split"
            params["split_pct"] = int(rest[i + 1])
            i += 1
        elif a == "--finestre":
            mode = "finestre"
            w, s = parse_finestre_arg(rest[i + 1])
            params["width_years"], params["step_years"] = w, s
            i += 1
        elif a == "--da":
            floor_year = int(rest[i + 1])
            i += 1
        elif a == "--volume":
            volume_on = True
        elif a == "--ore":
            ore = parse_ore_arg(rest[i + 1])
            i += 1
        else:
            raise ValueError(f"argomento non riconosciuto: {a}")
        i += 1
    return path, interval, threshold, window, baseline, mode, params, floor_year, volume_on, ore


def _ask(prompt, default):
    ans = input(f"{prompt} [{default}]: ").strip()
    return ans or default


def _wizard():
    console.print("[bold]Studio degli eventi[/bold] — rispondi alle domande (Invio = valore tra parentesi).\n")
    path = _ask("File CSV dei dati", "data/XBTEUR.csv")
    floor_year = int(_ask("Da quale anno in poi (min consigliato 2017)", str(FLOOR_YEAR_DEFAULT)))
    tf = _ask("Timeframe candela (15min/1h/4h/1g)", "15min")
    interval = TIMEFRAMES.get(tf, parse_duration_to_minutes(tf))
    threshold = float(_ask("Soglia variazione % col segno (es. -5)", "-5"))
    window = _ask("Finestra da osservare dopo (es. 4h, 1g)", "4h")
    baseline = _ask("Baseline (campione/tutte)", "campione")
    mode = _ask("Verifica stabilità (no/split/finestre)", "no")
    params = {}
    if mode == "split":
        params["split_pct"] = int(_ask("Percentuale in-sample", "70"))
    elif mode == "finestre":
        params["width_years"] = _years(_ask("Ampiezza finestra in anni", "1"))
        params["step_years"] = _years(_ask("Passo in anni", "1"))
    volume_on = _ask("Distinguere per volume (s/n)", "n").strip().lower() in ("s", "si", "sì", "y", "yes")
    ore = parse_ore_arg(_ask("Solo certe ore UTC? (INIZIO-FINE, vuoto = tutte)", ""))
    return path, interval, threshold, window, baseline, mode, params, floor_year, volume_on, ore


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        cfg = _parse_cli(argv) if argv else _wizard()
    except (ValueError, IndexError) as e:
        console.print(f"[red]Argomenti non validi: {e}[/red]")
        console.print("Uso: python -m lab.eventstudy "
                      "[CSV INTERVAL SOGLIA FINESTRA [campione|tutte] "
                      "[--split N | --finestre W:S] [--da ANNO] [--volume] [--ore I-F]]")
        return 1
    path, interval, threshold, window, baseline, mode, params, floor_year, volume_on, ore = cfg
    if threshold == 0:
        console.print("[red]La soglia non può essere 0.[/red]")
        return 1
    if ore is not None and interval >= 1440:
        console.print("[yellow]⚠ il filtro orario non ha effetto sul timeframe giornaliero[/yellow]")
        ore = None
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
        console.print(f"[yellow]⚠ stai includendo anni a liquidità sottile "
                      f"(pre-{FLOOR_YEAR_DEFAULT}): possibili falsi pattern[/yellow]")
    N = max(1, parse_duration_to_minutes(window) // interval)
    labels = tappe_labels(_tappe(N), interval)
    slices = slice_periods(candles, mode, params)
    verso = "≤" if threshold < 0 else "≥"
    title = (f"Eventi: candela {interval}min con variazione {verso} {threshold:+g}%  |  "
             f"finestra {window} (N={N})  |  baseline {baseline}  |  dal {floor_year}")
    if ore is not None:
        title += f"  |  ore {ore[0]}-{ore[1]} UTC"
    if volume_on:
        results = [(label, analyze_slice_volume(sub, threshold, N, baseline, ore=ore)) for label, sub in slices]
        render_report_volume(title + "  |  per volume", results, labels)
    else:
        results = [(label, analyze_slice(sub, threshold, N, baseline, ore=ore)) for label, sub in slices]
        render_report(title, results, labels)
    return 0


if __name__ == "__main__":
    sys.exit(main())
