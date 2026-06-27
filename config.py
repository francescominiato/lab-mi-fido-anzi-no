"""
Configurazione centrale del Paper Trading Lab.

Qui ci sono TUTTI i numeri che puoi cambiare per sperimentare.
Cambia un valore qui e tutto il resto (backtest e dashboard) si adegua.
"""

# --- Mercato ---------------------------------------------------------------
# Coppia da tradare. Su Kraken il Bitcoin contro euro si chiama "XBTEUR"
# (XBT = Bitcoin secondo lo standard ISO, EUR = euro).
# In Italia conviene l'euro: cosi' eviti il rischio nascosto del cambio euro/dollaro.
# Per tornare al dollaro: PAIR = "XBTUSD" (e CURRENCY = "$").
PAIR = "XBTEUR"

# Simbolo della valuta mostrato a schermo (deve combaciare con PAIR).
CURRENCY = "€"

# Timeframe in MINUTI di ogni candela. 15 = una candela ogni 15 minuti.
INTERVAL = 15

# Percorso del binario kraken installato dall'installer ufficiale.
KRAKEN_BIN = "~/.cargo/bin/kraken"


# --- Soldi finti del simulatore --------------------------------------------
# Capitale di partenza (in euro) per OGNI strategia (ognuna ha il suo conto).
START_CASH = 10_000.0

# Commissione per ogni operazione (compra o vendi), come frazione.
# 0.0026 = 0,26% = la fee "taker" reale di Kraken per chi inizia.
FEE_RATE = 0.0026


# --- Stop-loss (rete di protezione) ----------------------------------------
# Interruttore: True = acceso, False = spento.
# Quando acceso, se il prezzo scende sotto la soglia rispetto al prezzo di
# ingresso, si VENDE subito per limitare la perdita, anche se la strategia
# direbbe di tenere. E' la cintura di sicurezza contro i crolli.
STOP_LOSS_ON = False

# Di quanto puo' scendere il prezzo prima di scattare (frazione).
# 0.03 = 3% sotto il prezzo a cui hai comprato.
STOP_LOSS_PCT = 0.03


# --- Filtro di tendenza (semaforo generale) --------------------------------
# Interruttore: True = acceso, False = spento.
# Quando acceso, si COMPRA solo se il prezzo e' sopra la sua media lunga
# (mercato "in salita di fondo"). Se il prezzo e' sotto, si resta in contanti,
# qualunque cosa dica la strategia. Evita di "remare controcorrente" nei ribassi.
TREND_FILTER_ON = False

# Lunghezza (in candele) della media che definisce la tendenza di fondo.
# 200 candele da 15 min = circa 2 giorni di prezzo medio.
TREND_FILTER_PERIOD = 200


# --- Dimensionamento del rischio (no all-in) -------------------------------
# Interruttore: True = invece di investire TUTTO il capitale a ogni operazione,
# ne investiamo solo una parte, calibrata in modo da rischiare al massimo
# RISK_PER_TRADE_PCT del capitale se scatta lo stop-loss.
# Richiede lo stop-loss acceso (serve a definire "quanto si rischia").
POSITION_SIZING_ON = False

# Quanto capitale rischiare per ogni singola operazione (frazione).
# 0.01 = 1%. Con stop al 10%, si investe ~10% del capitale (1%/10%).
RISK_PER_TRADE_PCT = 0.01


# --- Parametri delle tre strategie -----------------------------------------
# 1) EMA crossover (segue il trend)
EMA_FAST = 9    # media mobile "veloce" (reagisce in fretta)
EMA_SLOW = 21   # media mobile "lenta" (reagisce piano)

# 2) RSI mean-reversion (scommette sul ritorno verso la media)
RSI_PERIOD = 14       # su quante candele si calcola l'RSI
RSI_OVERSOLD = 30     # sotto questo livello = "ipervenduto" -> COMPRA
RSI_OVERBOUGHT = 70   # sopra questo livello = "ipercomprato" -> VENDI

# 2b) Variante "RSI uscita alla media": entra come l'RSI (ipervenduto), ma ESCE
# quando il prezzo risale alla sua media (la "mean"), invece di aspettare RSI>70.
# Periodo della media-bersaglio (EMA). 50 e' il valore usato dalle guide pratiche.
RSI_EXIT_MEAN_PERIOD = 50

# 3) Breakout Donchian (cavalca le rotture)
BREAKOUT_LOOKBACK = 20  # rottura del massimo/minimo delle ultime N candele

# --- Classificatore di regime (rialzista / ribassista / laterale) ----------
# Distingue tre "stati" del mercato usando la pendenza di una media,
# normalizzata per la volatilita' (ATR). Vedi lab/regime.py.
REGIME_MA_PERIOD = 20       # media che definisce la tendenza di fondo (~20 giorni sul giornaliero)
REGIME_ATR_PERIOD = 14      # su quante candele si misura la volatilita' (standard Wilder)
REGIME_SLOPE_LOOKBACK = 20  # su quante candele si misura la pendenza della media
# Sotto questa "forza" (drift della media per candela, in unita' di ATR) il
# mercato e' considerato LATERALE. E' la manopola principale da tarare.
REGIME_FLAT_THRESHOLD = 0.05

# 4) TTM Squeeze (Carter): compressione BB→KC poi esplosione direzionale
SQUEEZE_PERIOD = 20     # periodo per BB, KC e momentum (standard Carter)
SQUEEZE_BB_MULT = 2.0   # moltiplicatore std per le Bollinger Bands
SQUEEZE_KC_MULT = 1.5   # moltiplicatore ATR per i Keltner Channels

# --- Dashboard live --------------------------------------------------------
# Ogni quanti secondi la dashboard ricarica i prezzi e ridisegna le finestre.
REFRESH_SECONDS = 60
