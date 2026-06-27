# Lab — Mi fido, anzi no

Questi sono gli strumenti del laboratorio descritti nel libro
[*«Mi fido, anzi no»*](https://www.amazon.it/dp/B0H6883VXR) di Francesco Miniato.

Backtest, walk-forward, event study, analisi on-chain, paper trading crypto e
simulatore forex: tutto quello che nel libro viene raccontato a parole, qui è
codice che il lettore può leggere, eseguire e modificare.

## Cosa serve

- **Python 3.12+**
- **rich** (unica dipendenza esterna: `pip install rich`)

## Dati

Gli script lavorano su file CSV di dati storici che vanno scaricati separatamente
(non sono inclusi nel repo per ragioni di dimensione).

| Dato | Fonte | Formato |
|---|---|---|
| BTC/EUR (trades) | [Kraken — Trading History](https://support.kraken.com/hc/en-us/articles/360047124832-Downloadable-historical-OHLCVT-Open-High-Low-Close-Volume-Trades-data) | ZIP trimestrali, estrarre `XBTEUR.csv` |
| EUR/USD (trades) | Kraken, stesso archivio | estrarre `EURUSD.csv` |
| On-chain BTC (MVRV, supply, ecc.) | [Coin Metrics — community data](https://coinmetrics.io/community-network-data/) | `onchain_btc.csv` |

Metti i file in una cartella `data/` accanto agli script.

## Panoramica degli script

### Motore

| Script | Ruolo |
|---|---|
| `config.py` | Parametri globali (timeframe, commissioni, stop-loss) |
| `data.py` | Caricamento dati, costruzione candele, cache |
| `strategies.py` | Strategie (RSI, EMA, breakout, trend-following) |
| `portfolio.py` | Simulatore di portafoglio con commissioni e stop-loss |

### Backtest e validazione

| Script | Ruolo |
|---|---|
| `backtest.py` | Backtest singolo su storia lunga |
| `sweep.py` | Griglia parametrica: tutte le combinazioni di strategia × soglie |
| `walkforward.py` | Walk-forward: studia il passato, opera sul futuro, ripeti *n* volte |

### Esperimenti

| Script | Cosa verifica |
|---|---|
| `exp_timeframe.py` | Confronto 15min / 1h / daily / 4h / settimanale |
| `exp_costi.py` | Impatto delle commissioni sui vari timeframe |
| `exp_short.py` | Long-only vs long+short |
| `exp_pricecheck.py` | Cross-check prezzi Kraken vs Coin Metrics |
| `eventstudy.py` | Event study: cosa succede dopo un evento di prezzo |
| `volstudy.py` | Studio della volatilità per fascia oraria e giorno |
| `regime.py` | Classificazione dei regimi di mercato |

### On-chain

| Script | Cosa fa |
|---|---|
| `onchain.py` | Scarica e aggiorna dati on-chain da Coin Metrics |
| `onchain_mvrv.py` | Analisi MVRV: zone di accumulo e distribuzione |
| `onchain_study.py` | Event study su segnali on-chain |
| `onchain_supply.py` | Analisi della supply fuori dagli exchange |
| `onchain_xcheck.py` | Cross-check tra fonti on-chain diverse |
| `dca_mvrv.py` | DCA potenziato con MVRV: accumulare di più nei saldi |
| `cruscotto.py` | Cruscotto on-chain: stato attuale degli indicatori |

### Paper trading

| Script | Cosa fa |
|---|---|
| `paper_cli.py` | CLI per paper trading BTC/EUR su Kraken (soldi finti, prezzi veri) |
| `dashboard.py` | Dashboard live del paper trading |
| `fx_paper.py` | Simulatore paper trading forex EUR/USD |

## Licenza

Codice rilasciato a scopo didattico e divulgativo.
