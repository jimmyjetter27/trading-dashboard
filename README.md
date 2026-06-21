# MetaTrader Trade Observer

Local MetaTrader 5 monitoring dashboard with:

- live open-trade cards
- entry / exit / take-profit / stop-loss / capital-risk alerts
- repeating alarm modal with a `Stop Alarm` button
- generated alert sounds in the browser and Windows beep support in the backend
- automatic SQLite logging
- a day-grouped journal with filters for date range, profit/loss, and lot size
- manual `Connect to MT5` and confirmed `Clear Database` actions
- dark mode and responsive layout
- ORL-25 Analysis Suite for live observer signals and historical past-chart analysis

## What it shows

- Direction (buy/sell)
- TP and SL
- Opening price
- Current price while open, then closing price in the history table after exit
- Live up/down price animation
- Trade ID
- Balance and equity
- Connected account login / server and initial balance before a trade starts
- Lot size
- Real-time pip movement
- Time entered
- Time exited in the journal

## Files

- `server.py` - backend monitor, SQLite writer, and local web server
- `orl_suite.py` - shared ORL-25 calculation engine used by both live and historical modes
- `web/` - dashboard UI
- `trade_observer.sqlite3` - auto-created database
- `.env.example` - ORL-25 environment configuration reference

## Install

Use a Python runtime that has the `MetaTrader5` package available:

```powershell
pip install -r requirements.txt
```

## Run

Double-click:

```text
run_metatrader_trade_observer.bat
```

This launcher starts the local Python server first, waits until it is live, and then opens:
Keep the launcher terminal window open while you use the dashboard, then manually open:

```text
http://127.0.0.1:8765
```

Do not open `web/index.html` directly as a file for normal use, because that does not start the local server.

Or from PowerShell:

```powershell
.\run_metatrader_trade_observer.ps1
```

## Notes

- MetaTrader 5 must be installed and logged into the trading account you want to watch.
- If the dashboard still shows `MT5 Disconnected`, click `Connect to MT5` after the page loads.
- The app uses the first open position symbol, or falls back to common gold symbol names if nothing is open yet.
- Stop warning and capital-risk thresholds are set in `AppConfig` inside `server.py`.
- If the MetaTrader5 package is missing, the dashboard still opens and shows the connection error instead of crashing.
- ORL-25 historical analysis is available from the Analysis page through `Analyze Past Chart`.
- ORL-25 live alerts analyze only and do not place trades.
