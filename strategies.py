"""
Le tre strategie del Lab.

Ogni strategia trasforma la lista di candele in una "serie di posizioni":
per ogni candela dice se vogliamo essere DENTRO il mercato (1 = LONG, abbiamo
comprato) oppure FUORI (0 = FLAT, siamo in dollari).

Regola anti-imbroglio (no lookahead): la posizione alla candela i usa SOLO i
dati fino alla candela i compresa. Nessuna strategia "sbircia" il futuro.

Tutte le strategie sono LONG-ONLY: o compriamo o stiamo liquidi, mai short.
"""

from dataclasses import dataclass
from typing import Callable

from . import config
from .data import Candle


# --- Indicatori (mattoncini riutilizzabili) --------------------------------

def ema(values: list[float], period: int) -> list[float | None]:
    """
    Media mobile esponenziale. Da' piu' peso ai prezzi recenti.
    Restituisce None finche' non ci sono abbastanza dati per partire.
    """
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    # Primo valore EMA = media semplice delle prime `period` chiusure.
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: list[float], period: int) -> list[float | None]:
    """
    RSI (Relative Strength Index), 0-100. Misura quanto un prezzo e' "tirato".
    Usa lo smoothing di Wilder, lo standard classico.
    """
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period

    def rsi_from(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return 100 - (100 / (1 + rs))

    out[period] = rsi_from(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = rsi_from(avg_gain, avg_loss)
    return out


def atr(candles: list[Candle], period: int) -> list[float | None]:
    """
    ATR (Average True Range): quanto "di solito" si muove una candela, in valore
    assoluto di prezzo. Usa lo smoothing di Wilder, come l'RSI.
    Restituisce None finche' non c'e' abbastanza storia.
    """
    out: list[float | None] = [None] * len(candles)
    if len(candles) <= period:
        return out
    # True Range di ogni candela (il primo non ha close precedente).
    trs: list[float] = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c.high - c.low)
        else:
            prev_close = candles[i - 1].close
            trs.append(max(c.high - c.low,
                           abs(c.high - prev_close), abs(c.low - prev_close)))
    # Primo ATR = media semplice dei TR da 1 a period (period valori).
    avg = sum(trs[1:period + 1]) / period
    out[period] = avg
    for i in range(period + 1, len(candles)):
        avg = (avg * (period - 1) + trs[i]) / period
        out[i] = avg
    return out


def sma(values: list[float], period: int) -> list[float | None]:
    """Media mobile semplice. Usata dalle Bollinger Bands."""
    out: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i - period + 1:i + 1]) / period
    return out


def bollinger_bands(
    closes: list[float], period: int, mult: float
) -> tuple[list[float | None], list[float | None]]:
    """Upper e lower delle Bollinger Bands (SMA ± mult×std)."""
    mid = sma(closes, period)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        m = mid[i]
        window = closes[i - period + 1:i + 1]
        std = (sum((x - m) ** 2 for x in window) / period) ** 0.5
        upper[i] = m + mult * std
        lower[i] = m - mult * std
    return upper, lower


def keltner_channels(
    candles: list[Candle], period: int, mult: float
) -> tuple[list[float | None], list[float | None]]:
    """Upper e lower dei Keltner Channels (EMA ± mult×ATR)."""
    closes = [c.close for c in candles]
    mid = ema(closes, period)
    atr_vals = atr(candles, period)
    upper: list[float | None] = [None] * len(candles)
    lower: list[float | None] = [None] * len(candles)
    for i in range(len(candles)):
        if mid[i] is not None and atr_vals[i] is not None:
            upper[i] = mid[i] + mult * atr_vals[i]
            lower[i] = mid[i] - mult * atr_vals[i]
    return upper, lower


def squeeze_momentum(candles: list[Candle], period: int) -> list[float | None]:
    """
    Momentum histogram del TTM Squeeze (formula Carter/TOS):
    delta = close - media((highest_high_N + lowest_low_N)/2, SMA(close, N))
    Positivo = momentum bullish, negativo = bearish.
    """
    closes = [c.close for c in candles]
    sma_vals = sma(closes, period)
    mom: list[float | None] = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        hh = max(c.high for c in candles[i - period + 1:i + 1])
        ll = min(c.low  for c in candles[i - period + 1:i + 1])
        mom[i] = closes[i] - ((hh + ll) / 2 + sma_vals[i]) / 2
    return mom


# --- Le tre strategie -------------------------------------------------------

def strat_ema_cross(candles: list[Candle]) -> tuple[list[int], dict]:
    """Trend-following: dentro quando l'EMA veloce sta sopra la lenta."""
    closes = [c.close for c in candles]
    fast = ema(closes, config.EMA_FAST)
    slow = ema(closes, config.EMA_SLOW)
    positions = [0] * len(candles)
    for i in range(len(candles)):
        if fast[i] is not None and slow[i] is not None:
            positions[i] = 1 if fast[i] > slow[i] else 0
    return positions, {"ema_fast": fast, "ema_slow": slow}


def strat_rsi_reversion(candles: list[Candle]) -> tuple[list[int], dict]:
    """Mean-reversion: compra in ipervenduto, vende in ipercomprato, tiene in mezzo."""
    closes = [c.close for c in candles]
    values = rsi(closes, config.RSI_PERIOD)
    positions = [0] * len(candles)
    pos = 0
    for i in range(len(candles)):
        r = values[i]
        if r is not None:
            if pos == 0 and r < config.RSI_OVERSOLD:
                pos = 1                       # entra: prezzo "troppo basso"
            elif pos == 1 and r > config.RSI_OVERBOUGHT:
                pos = 0                       # esci: prezzo "troppo alto"
        positions[i] = pos
    return positions, {"rsi": values}


def strat_rsi_mean_exit(candles: list[Candle]) -> tuple[list[int], dict]:
    """
    Variante mean-reversion "da manuale": entra quando ipervenduto (RSI < 30),
    ma ESCE quando il prezzo torna alla sua media (EMA), invece di aspettare
    RSI > 70. Cura il difetto dell'RSI classico nei ribassi prolungati, dove
    RSI > 70 non arriva mai e si resta dentro mentre il prezzo affonda.
    """
    closes = [c.close for c in candles]
    rsi_vals = rsi(closes, config.RSI_PERIOD)
    mean = ema(closes, config.RSI_EXIT_MEAN_PERIOD)
    positions = [0] * len(candles)
    pos = 0
    for i in range(len(candles)):
        r = rsi_vals[i]
        m = mean[i]
        if r is not None and m is not None:
            if pos == 0 and r < config.RSI_OVERSOLD:
                pos = 1                                  # ipervenduto -> entra
            elif pos == 1 and (closes[i] >= m or r > config.RSI_OVERBOUGHT):
                pos = 0                                  # tornato alla media -> esci
        positions[i] = pos
    return positions, {"rsi": rsi_vals, "ema_mean": mean}


def strat_breakout(candles: list[Candle]) -> tuple[list[int], dict]:
    """Breakout: entra rompendo il massimo recente, esce sotto il minimo recente."""
    n = config.BREAKOUT_LOOKBACK
    highs: list[float | None] = [None] * len(candles)
    lows: list[float | None] = [None] * len(candles)
    positions = [0] * len(candles)
    pos = 0
    for i in range(len(candles)):
        if i >= n:
            # Canale calcolato sulle N candele PRECEDENTI (escludo la corrente).
            window = candles[i - n:i]
            ch_high = max(c.high for c in window)
            ch_low = min(c.low for c in window)
            highs[i] = ch_high
            lows[i] = ch_low
            if pos == 0 and candles[i].close > ch_high:
                pos = 1                       # rottura al rialzo -> entra
            elif pos == 1 and candles[i].close < ch_low:
                pos = 0                       # cede il supporto -> esci
        positions[i] = pos
    return positions, {"donchian_high": highs, "donchian_low": lows}


def strat_squeeze(candles: list[Candle]) -> tuple[list[int], dict]:
    """
    TTM Squeeze (Carter): entra long quando la compressione di volatilita'
    (Bollinger Bands dentro i Keltner Channels = dot nero) si libera con
    momentum positivo (dot grigio + histogram > 0). Esce quando il momentum
    gira negativo. Long-only, niente short.
    """
    period = config.SQUEEZE_PERIOD
    closes = [c.close for c in candles]
    bb_up, bb_lo = bollinger_bands(closes, period, config.SQUEEZE_BB_MULT)
    kc_up, kc_lo = keltner_channels(candles, period, config.SQUEEZE_KC_MULT)
    mom = squeeze_momentum(candles, period)

    # in_squeeze[i] = True se le BB sono dentro i KC (compressione attiva)
    in_sq: list[bool | None] = [None] * len(candles)
    for i in range(len(candles)):
        if all(v is not None for v in [bb_up[i], bb_lo[i], kc_up[i], kc_lo[i]]):
            in_sq[i] = (bb_up[i] - bb_lo[i]) < (kc_up[i] - kc_lo[i])

    positions = [0] * len(candles)
    pos = 0
    for i in range(1, len(candles)):
        m = mom[i]
        if m is None or in_sq[i] is None or in_sq[i - 1] is None:
            positions[i] = pos
            continue
        if pos == 0 and in_sq[i - 1] and not in_sq[i] and m > 0:
            pos = 1   # squeeze si libera bullish (dot grigio + momentum > 0)
        elif pos == 1 and m < 0:
            pos = 0   # momentum gira negativo -> esci
        positions[i] = pos

    return positions, {"squeeze_mom": mom, "in_squeeze": in_sq}


# --- Registro delle strategie ----------------------------------------------

@dataclass
class Strategy:
    key: str
    name: str            # nome breve per le finestre
    description: str     # una riga di spiegazione
    func: Callable[[list[Candle]], tuple[list[int], dict]]


STRATEGIES: list[Strategy] = [
    Strategy(
        "ema",
        "EMA crossover",
        f"Segue il trend (EMA {config.EMA_FAST} vs {config.EMA_SLOW})",
        strat_ema_cross,
    ),
    Strategy(
        "rsi",
        "RSI reversion",
        f"Compra ipervenduto <{config.RSI_OVERSOLD}, vende >{config.RSI_OVERBOUGHT}",
        strat_rsi_reversion,
    ),
    Strategy(
        "rsi_mean",
        "RSI->media",
        f"Entra <{config.RSI_OVERSOLD}, esce al ritorno alla media EMA{config.RSI_EXIT_MEAN_PERIOD}",
        strat_rsi_mean_exit,
    ),
    Strategy(
        "breakout",
        "Breakout",
        f"Rompe il massimo delle ultime {config.BREAKOUT_LOOKBACK} candele",
        strat_breakout,
    ),
    Strategy(
        "squeeze",
        "TTM Squeeze",
        f"Compressione BB/KC→momentum (periodo {config.SQUEEZE_PERIOD})",
        strat_squeeze,
    ),
]


def signal_label(prev_pos: int, pos: int) -> str:
    """Traduce il cambio di posizione in un'azione leggibile."""
    if prev_pos == 0 and pos == 1:
        return "COMPRA"
    if prev_pos == 1 and pos == 0:
        return "VENDI"
    if pos == 1:
        return "MANTIENI"
    return "ASPETTA"
