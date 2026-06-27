"""
Recupero dati di mercato dalla CLI ufficiale di Kraken.

Non parliamo MAI direttamente con le API di Kraken: chiediamo tutto al binario
`kraken` (gia' installato) con output in JSON, cosi' restiamo semplici e sicuri.
Servono solo dati PUBBLICI -> nessuna chiave API, nessun rischio.
"""

import csv
import json
import os
import subprocess
from dataclasses import dataclass

from . import config


@dataclass
class Candle:
    """Una singola candela OHLC (Open/High/Low/Close)."""
    ts: int        # timestamp UNIX (inizio della candela)
    open: float
    high: float
    low: float
    close: float
    volume: float


def _kraken(*args: str) -> dict:
    """Esegue `kraken ... -o json` e restituisce il JSON gia' parsato."""
    binary = os.path.expanduser(config.KRAKEN_BIN)
    cmd = [binary, *args, "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(
            f"Comando kraken fallito: {' '.join(args)}\n{result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def fetch_candles(pair: str = config.PAIR, interval: int = config.INTERVAL) -> list[Candle]:
    """
    Scarica lo storico delle candele per la coppia/timeframe indicati.

    Kraken restituisce un dizionario con la chiave del nome "lungo" della coppia
    (es. XBTUSD -> XXBTZUSD) piu' una chiave 'last'. Prendiamo l'unica lista di
    candele presente, qualunque sia il nome esatto della chiave.
    """
    raw = _kraken("ohlc", pair, "--interval", str(interval))
    # Troviamo la chiave che contiene la lista di candele (tutto tranne 'last').
    series_key = next(k for k in raw if k != "last")
    rows = raw[series_key]

    candles: list[Candle] = []
    for row in rows:
        # Formato riga: [ts, open, high, low, close, vwap, volume, count]
        candles.append(
            Candle(
                ts=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[6]),
            )
        )
    return candles


def _is_number(x: str) -> bool:
    try:
        float(x)
        return True
    except ValueError:
        return False


def _parse_ohlcvt(rows) -> list[Candle]:
    """Legge righe gia' in formato candela: timestamp, open, high, low, close, volume[, ...]."""
    candles: list[Candle] = []
    for row in rows:
        if len(row) < 6 or not _is_number(row[0]):
            continue
        ts = int(float(row[0]))
        o, h, l, c = float(row[1]), float(row[2]), float(row[3]), float(row[4])
        vol = float(row[6]) if len(row) >= 8 else float(row[5])
        candles.append(Candle(ts=ts, open=o, high=h, low=l, close=c, volume=vol))
    candles.sort(key=lambda x: x.ts)
    return candles


def _write_candle_cache(cache_path: str, candles: list[Candle]) -> None:
    """Salva le candele aggregate in un piccolo CSV OHLCVT, per ricaricarle al volo."""
    try:
        with open(cache_path, "w", newline="") as f:
            w = csv.writer(f)
            for c in candles:
                w.writerow([c.ts, c.open, c.high, c.low, c.close, c.volume])
    except OSError:
        pass  # la cache e' un optional: se non si puo' scrivere, pazienza


def load_candles_csv(path: str, interval: int = config.INTERVAL) -> list[Candle]:
    """
    Carica le candele da un file CSV storico di Kraken. Riconosce DA SOLO tre formati:

    1) Trades con intestazione (formato attuale di Kraken Trading History):
       colonne "Price, Volume, Timestamp, Type, ...". Le ritroviamo PER NOME.
    2) Trades grezzi senza intestazione, 3 colonne: timestamp, prezzo, volume.
    3) OHLCVT (candele gia' pronte, es. "XBTEUR_15.csv"): senza intestazione,
       timestamp, open, high, low, close, volume, n_scambi (>= 6 colonne).

    Per i formati "trades" (1 e 2) costruiamo noi le candele aggregando sul timeframe,
    e salviamo una CACHE accanto al file (es. "XBTEUR.csv.c15.csv"): la prima volta e'
    lenta (milioni di righe), le successive ricarica la cache in un attimo.
    """
    path = os.path.expanduser(path)

    # Cache: se esiste ed e' piu' recente del file sorgente, usala (veloce).
    cache_path = f"{path}.c{interval}.csv"
    if os.path.exists(cache_path) and os.path.getmtime(cache_path) >= os.path.getmtime(path):
        with open(cache_path, newline="") as f:
            cached = _parse_ohlcvt(csv.reader(f))
        if cached:
            return cached

    with open(path, newline="") as f:
        reader = csv.reader(f)
        first = next((r for r in reader if r), None)
        if first is None:
            raise RuntimeError(f"File vuoto: {path}")

        header = None if _is_number(first[0]) else [c.strip().lower() for c in first]

        # Generatore delle righe-dati (riusa la prima riga se NON era un'intestazione).
        def data_rows():
            if header is None:
                yield first
            for r in reader:
                if r:
                    yield r

        from_trades = False
        if header is not None:
            # Formato 1: trades con intestazione -> colonne per nome.
            if {"price", "volume", "timestamp"} <= set(header):
                idx = (header.index("timestamp"), header.index("price"),
                       header.index("volume"))
                candles = _candles_from_trades(data_rows(), interval, idx)
                from_trades = True
            else:
                raise RuntimeError(
                    f"Intestazione CSV non riconosciuta in {path}: {first}"
                )
        elif len(first) == 3:
            # Formato 2: trades grezzi (timestamp, prezzo, volume).
            candles = _candles_from_trades(data_rows(), interval, (0, 1, 2))
            from_trades = True
        else:
            # Formato 3: OHLCVT (candele gia' pronte).
            candles = _parse_ohlcvt(data_rows())

    if not candles:
        raise RuntimeError(f"Nessuna candela valida trovata in {path}")
    if from_trades:
        _write_candle_cache(cache_path, candles)  # accelera i caricamenti futuri
    return candles


def load_candles_csv_many(paths: list[str], interval: int = config.INTERVAL) -> list[Candle]:
    """
    Carica e UNISCE piu' file CSV (es. trimestri diversi) in un'unica serie di candele,
    ordinata per data e senza doppioni (se due file si sovrappongono al confine).
    """
    by_ts: dict[int, Candle] = {}
    for p in paths:
        for candle in load_candles_csv(p, interval):
            by_ts[candle.ts] = candle  # in caso di doppio timestamp, tiene l'ultimo letto
    return [by_ts[ts] for ts in sorted(by_ts)]


def _candles_from_trades(rows, interval: int, idx: tuple[int, int, int]) -> list[Candle]:
    """
    Aggrega gli scambi grezzi in candele OHLC da `interval` minuti.
    `idx` = (colonna_timestamp, colonna_prezzo, colonna_volume).
    """
    ts_i, p_i, v_i = idx
    size = interval * 60  # ampiezza del "secchiello" in secondi
    buckets: dict[int, dict] = {}
    for row in rows:
        # Salta righe troppo corte o sporche senza far esplodere il caricamento.
        if len(row) <= max(idx) or not _is_number(row[ts_i]):
            continue
        ts = int(float(row[ts_i]))
        price = float(row[p_i])
        vol = float(row[v_i])
        b = ts - (ts % size)  # inizio della candela a cui appartiene lo scambio
        e = buckets.get(b)
        if e is None:
            buckets[b] = {"min": ts, "max": ts, "o": price, "c": price,
                          "h": price, "l": price, "v": vol}
        else:
            if ts <= e["min"]:
                e["min"], e["o"] = ts, price
            if ts >= e["max"]:
                e["max"], e["c"] = ts, price
            e["h"] = max(e["h"], price)
            e["l"] = min(e["l"], price)
            e["v"] += vol
    return [
        Candle(ts=b, open=e["o"], high=e["h"], low=e["l"], close=e["c"], volume=e["v"])
        for b, e in sorted(buckets.items())
    ]


def fetch_last_price(pair: str = config.PAIR) -> float:
    """Restituisce l'ultimo prezzo scambiato (per la dashboard live)."""
    raw = _kraken("ticker", pair)
    info = next(v for v in raw.values())  # primo (e unico) valore del dizionario
    # Il ticker espone 'c' = [prezzo ultimo scambio, volume]. Fallback su 'last'.
    if isinstance(info, dict) and "c" in info:
        return float(info["c"][0])
    raise RuntimeError(f"Formato ticker inatteso: {raw}")
