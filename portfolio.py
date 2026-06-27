"""
Simulatore di portafoglio (soldi finti).

Data una strategia (la sua serie di posizioni 0/1) e le candele, simula compere
e vendite e calcola com'e' andata: equity finale, rendimento, numero di
operazioni, percentuale di operazioni vincenti e il "drawdown" massimo (la
peggior discesa subita dal picco).

Modello semplice e didattico:
- LONG-ONLY: o tutto comprato o tutto liquido (no leva, no short).
- ALL-IN: quando compriamo, usiamo tutto il contante; quando vendiamo, tutto.
- Si compra/vende alla CHIUSURA della candela in cui scatta il segnale.
- Ogni operazione paga la commissione FEE_RATE.
"""

from dataclasses import dataclass, field

from . import config
from .data import Candle


@dataclass
class BacktestResult:
    final_equity: float
    return_pct: float
    num_trades: int          # operazioni complete (compra+vendi)
    win_rate_pct: float      # % di operazioni chiuse in guadagno
    max_drawdown_pct: float  # peggior discesa dal picco (numero negativo)
    equity_curve: list[float] = field(default_factory=list)


def _sma(values: list[float], period: int) -> list[float | None]:
    """Media mobile semplice: media degli ultimi `period` valori. None finche' scarseggiano."""
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    running = sum(values[:period])
    out[period - 1] = running / period
    for i in range(period, len(values)):
        running += values[i] - values[i - period]
        out[i] = running / period
    return out


def run_backtest(
    candles: list[Candle],
    positions: list[int],
    start_cash: float = config.START_CASH,
    fee_rate: float = config.FEE_RATE,
    stop_loss_on: bool = config.STOP_LOSS_ON,
    stop_loss_pct: float = config.STOP_LOSS_PCT,
    trend_filter_on: bool = config.TREND_FILTER_ON,
    trend_filter_period: int = config.TREND_FILTER_PERIOD,
    position_sizing: bool = config.POSITION_SIZING_ON,
    risk_pct: float = config.RISK_PER_TRADE_PCT,
) -> BacktestResult:
    # FILTRO DI TENDENZA: se acceso, azzeriamo i segnali di acquisto quando il
    # prezzo e' sotto la sua media lunga (mercato "in discesa di fondo"). Cosi'
    # il resto del motore lavora gia' sui segnali "filtrati".
    if trend_filter_on:
        sma = _sma([c.close for c in candles], trend_filter_period)
        positions = [
            p if (sma[i] is not None and candles[i].close > sma[i]) else 0
            for i, p in enumerate(positions)
        ]

    cash = start_cash
    btc = 0.0
    in_position = False
    cash_at_entry = start_cash      # contante prima di entrare (per il P&L del trade)
    entry_price = 0.0              # prezzo BTC a cui siamo entrati (per lo stop)
    wins = 0
    trades = 0
    equity_curve: list[float] = []

    for i, candle in enumerate(candles):
        want = positions[i]
        prev_want = positions[i - 1] if i > 0 else 0
        price = candle.close

        # ENTRATA: solo su un segnale FRESCO (la strategia passa da 0 a 1).
        # Cosi', dopo uno stop, NON si rientra subito solo perche' la strategia
        # e' ancora "lunga": si aspetta un nuovo segnale vero.
        if not in_position and prev_want == 0 and want == 1:
            cash_at_entry = cash
            entry_price = price
            # Quanto capitale impegnare: tutto (all-in) oppure solo la frazione che
            # fa rischiare al massimo risk_pct se scatta lo stop (position sizing).
            if position_sizing and stop_loss_on and stop_loss_pct > 0:
                frac = min(1.0, risk_pct / stop_loss_pct)
            else:
                frac = 1.0
            invest = cash * frac
            btc = invest * (1 - fee_rate) / price
            cash -= invest                 # il resto rimane liquido
            in_position = True

        elif in_position:
            stop_price = entry_price * (1 - stop_loss_pct)
            # USCITA 1 — stop-loss: se nella candela il prezzo tocca la soglia,
            # vendiamo al prezzo di stop (la rete di protezione ha la priorita').
            if stop_loss_on and candle.low <= stop_price:
                cash += btc * stop_price * (1 - fee_rate)
                btc = 0.0
                in_position = False
                trades += 1
                if cash > cash_at_entry:
                    wins += 1
            # USCITA 2 — segnale della strategia (es. RSI sopra 70).
            elif want == 0:
                cash += btc * price * (1 - fee_rate)
                btc = 0.0
                in_position = False
                trades += 1
                if cash > cash_at_entry:
                    wins += 1

        # Valore del portafoglio a fine candela (contante + BTC valorizzato).
        equity_curve.append(cash + btc * price)

    # Se a fine storico siamo ancora dentro, chiudiamo virtualmente per i conti.
    if in_position:
        last_price = candles[-1].close
        cash += btc * last_price * (1 - fee_rate)
        trades += 1
        if cash > cash_at_entry:
            wins += 1
        equity_curve[-1] = cash

    final_equity = equity_curve[-1] if equity_curve else start_cash
    return BacktestResult(
        final_equity=final_equity,
        return_pct=(final_equity / start_cash - 1) * 100,
        num_trades=trades,
        win_rate_pct=(wins / trades * 100) if trades else 0.0,
        max_drawdown_pct=_max_drawdown(equity_curve),
        equity_curve=equity_curve,
    )


def buy_and_hold(
    candles: list[Candle],
    start_cash: float = config.START_CASH,
    fee_rate: float = config.FEE_RATE,
) -> BacktestResult:
    """Benchmark: compri all'inizio e tieni fino alla fine. Il metro di paragone."""
    positions = [1] * len(candles)
    # Il "pigro" non usa ne' stop ne' filtro: tiene e basta, qualunque cosa accada.
    return run_backtest(candles, positions, start_cash, fee_rate,
                        stop_loss_on=False, trend_filter_on=False)


def _max_drawdown(equity_curve: list[float]) -> float:
    """Peggior calo percentuale dal massimo raggiunto fino a un minimo successivo."""
    peak = float("-inf")
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        drop = (value / peak - 1) * 100
        worst = min(worst, drop)
    return worst
