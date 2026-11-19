# NSE Breakout & Momentum Scanner

A daily stock scanner for the Indian market (NSE). It scans about 1,450 stocks after the close and lists
breakouts, breakdowns, momentum leaders and laggards, and stocks at all-time highs, in a local web app with charts,
a stop-loss / target calculator, and optional Zerodha Kite integration for placing GTT orders.

> **Not investment advice.** This is a rule-based technical screen. Scores rank stocks by fixed criteria and say
> nothing certain about future returns. Check every trade yourself.

## Features

- **11 screeners in one picker**, grouped as Long, Short and All-time highs (details below).
- **Top picks**, gated by rules that held up in a 4-year backtest; never padded to fill a quota.
- **Daily and weekly candle charts** for every listed stock, with the level being tested drawn in.
- **Fundamentals toggles**: a 0-100 score from six checks, and a filter that hides weak companies and shows why each
  remaining stock passed.
- **Cap-segment filter**: Large (Nifty 100), Mid (Midcap 150), Small (Smallcap 250), Micro (Microcap 250), Other.
- **Stop-loss & target calculator** sized from your capital, risk per trade and reward : risk.
- **Zerodha Kite integration** (optional): open any stock's chart in Kite, read your holdings and positions, and
  place stop-loss + target GTT orders after a review step.
- **Scan history**: every day's report is kept and can be reopened from a date picker.
- **Installable on a phone** as a home-screen web app over your home Wi-Fi.
- **Backtesting tools** to replay the scanner over past years.

## Quick start

Requires Python 3.9 or later.

```bash
git clone <your-repo-url> nse-scanner
cd nse-scanner
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

`app.py` opens http://localhost:8765. Press **Run new scan**; the first scan downloads two years of prices plus
each stock's full price history and takes several minutes. Later scans use caches and take about a minute. Run
scans after the market closes: NSE's end-of-day data is usually available from about 6 PM IST.

To scan from the terminal instead:

```bash
.venv/bin/python scan.py --open
```

## The screeners

The universe is every NSE EQ-series stock with a market cap of at least ₹1,000 crore, plus all Nifty 200 members.
The main scan skips stocks with under 200 days of history or a median daily traded value below ₹1 crore.

| Group | Screener | What it lists |
|---|---|---|
| Long | Top picks: long | Fresh daily breakouts that pass every gate: score 75+, industry RS 60+, not more than 4 ATR above the 50-day average, at least ₹5 crore traded a day, clean data. Up to 10 |
| Long | Near misses | Breakouts that failed exactly one top-pick gate, with the gate named |
| Long | All breakouts | Closed above the prior 20-day high today, or above the 20-week high this week, or both |
| Long | Setups near a breakout | Above the 50-day average and within 1.5 ATR below the 20-day high |
| Long | Momentum leaders | RS 70+ and above both the 50- and 200-day averages |
| Short | Top picks: short | Fresh breakdowns in F&O stocks with score 75+, RS 30 or lower, below the 200-day average, volume 1.5×+. **Not validated** by the backtest |
| Short | All breakdowns / Setups / Momentum laggards | Mirror images of the long lists |
| All-time highs | 1. All-time high breakouts | Market cap ₹1,000 crore+ and today's close above the previous all-time high (intraday highs included). Touching it intraday is not enough |
| All-time highs | 2. Recent IPOs at all-time highs | Screener 1, limited to IPOs from the last 12 months (toggle to 6). Companies that already traded on BSE or NSE before listing are not IPOs |
| All-time highs | 3. Pullbacks after an all-time-high breakout | Broke out in the last 10 sessions, pulled back below its newest high, still closing above the level it broke. Closest to that level first |

The all-time high covers each stock's full history: monthly bars for anything older than two years, daily bars for
the rest. At least 5 sessions of history are required.

### How scores work

Thresholds live in `Params` in `scanner/signals.py`.

| Score | Components |
|---|---|
| Breakout (triggered) | 35% volume surge (1× → 0, 3× → full), 30% relative strength, 15% thrust (ATRs closed past the level), 10% market breadth, 10% trend |
| Breakout setup | 35% relative strength, 30% proximity to the level, 15% trend, 10% market breadth, 10% up/down volume |
| Breakdown / breakdown setup | 30% proximity, 20% volatility squeeze, 15% trend, 15% relative weakness, 10% volume, 10% level significance |
| Momentum | 50% RS rating, 20% moving-average stack, 20% distance from the 52-week extreme, 10% ADX |

The RS rating is a stock's percentile (1-99) in the scanned universe on a blended 3/6/9/12-month return, weighted
40/20/20/20.

### Fundamentals

Six checks from Yahoo's latest reported figures (`scanner/fundamentals.py`, cached for a week): profitable,
ROE ≥ 12%, revenue growing, earnings growing, debt / equity below 1, and positive operating cash flow (the last two
are skipped for financial companies). The score is the share of checks passed. A stock is "fundamentally strong" if
it is profitable, has data for at least four checks and passes two thirds of them. These thresholds are untested
defaults.

## Stop-loss & target calculator

Menu → **SL & target calculator**. Enter capital, risk per trade (% of capital) and reward : risk, then either:

- **From my stop**: a stop as % away, a ₹ price, or a multiple of ATR (the stock's average daily range). The position
  is sized so that hitting the stop loses exactly your risk amount.
- **From my position**: an amount or number of shares. The stop is placed where the loss equals your risk amount.

It returns the stop-loss, target, quantity, position value, loss and profit at each, and the break-even win rate.
Each stock in the scanner has an "SL / target" link that opens the calculator with its price filled in.

## Zerodha Kite integration (optional)

Stock names link to their charts in Kite with no setup. Reading your account and placing orders needs a Kite
Connect app:

1. Create an app at https://developers.kite.trade with the redirect URL `http://localhost:8765/kite/callback`.
2. Open the calculator once; it creates `data/kite.json`. Put your `api_key` and `api_secret` there. This file is in
   `.gitignore` and must never be committed.
3. Press **Connect to Zerodha** and log in on Zerodha's own page. Zerodha's token expires daily, so this is needed
   once each trading day.

Then:

- **Calculator → Place in Zerodha** places the stop-loss and target as one two-leg GTT (one cancels the other) on
  shares you already hold.
- **Menu → Portfolio & GTT** lists your holdings and positions, shows which already have a GTT, and proposes a
  stop-loss and target for the rest from your capital, risk % and reward : risk. Short futures get buy legs.
  Intraday (MIS) positions can't have a GTT.

Safety:

- **Review before sending.** Nothing is sent to Zerodha until you review the exact order and confirm it.
- **This computer only.** Account and order features are refused for any request that doesn't come from the
  computer running the app, even in `--lan` mode.
- **Stop limit buffer.** A GTT places a limit order when it triggers. The stop's limit sits a buffer (default 0.5%)
  beyond its trigger so it can still fill in a fast move; a gap larger than that may leave it unfilled.
- **Test with one share first.** The integration was tested against a local stand-in for Zerodha's API, not a
  real account. Place your first GTT on one share and check it in Kite under Orders → GTT.

## Using it on a phone

```bash
.venv/bin/python app.py --lan
```

This prints an address such as `http://192.168.1.20:8765`. Open it in Safari on a phone on the same Wi-Fi, tap
Share, then **Add to Home Screen**. With `--lan`, anyone on that network can view scans and start one, but account
and order features stay limited to the computer running the app.

## Command-line options

```text
scan.py [--top N] [--refresh] [--fresh-prices] [--asof YYYY-MM-DD] [--universe all|nifty200]
        [--min-cap CRORE] [--min-turnover CRORE] [--verbose] [--open]
app.py  [--port 8765] [--lan] [--no-open]
```

Each scan writes to `reports/`:

| File | Contents |
|---|---|
| `scan_<date>.html` | The report |
| `scan_<date>.csv` | Every metric for every scanned stock |
| `scan_<date>_ath.csv` | All-time-high screeners 1 and 2 |
| `scan_<date>_ath_pullbacks.csv` | Screener 3 |
| `scan_<date>_fundamentals.csv` | Fundamental checks for every listed stock |

## Backtesting

```bash
.venv/bin/python backtest.py
```

```bash
.venv/bin/python variants.py
```

`backtest.py` replays the scanner over 5 years, enters each signal at the next day's open and measures returns 5,
10 and 20 days later against the average scanned stock. `variants.py` tests stricter breakout filters on those
signals, split at 1 Jan 2025 into two halves.

Findings (Nov 2022 to Nov 2026, about 1,330 stocks):

- **Breakouts:** plain 20-day breakouts slightly lagged the average stock.
- **Breakout score:** breakouts scoring 80+ beat it by about 0.5% over 20 days in both halves.
- **Long top picks:** the top-pick gates beat it by about 1.5% over 20 days in each half, with about half of the
  picks beating it individually.
- **Short side:** no rule held up in both halves.

Limits: today's stock list is applied to the past (survivorship bias), costs and slippage are excluded, and the
gates were chosen after seeing both halves. The all-time-high screeners and fundamentals checks are not backtested.

## Data sources and limitations

- **Prices:** Yahoo Finance (daily, adjusted for splits and dividends). If Yahoo has not published a trading day,
  the scan fills it from NSE's official end-of-day file and says so in the report.
- **Stock lists and index members:** NSE.
- **Market caps and fundamentals:** Yahoo Finance. Coverage is patchy for small and newly listed companies.
- **Unofficial access:** Yahoo Finance is reached through the unofficial `yfinance` library, which can be
  rate-limited or break without notice. The scan reports gaps instead of failing silently where it can.

## Project layout

```text
app.py                 local web app: reports, scan history, calculator, portfolio
scan.py                runs a scan and writes the report
backtest.py            replays the scanner over history
variants.py            tests breakout filter variants on backtest results
scanner/
  universe.py          stock universe, cap segments, IPO dates, Kite instrument tokens
  data.py              prices (Yahoo, NSE fallback), full-history highs
  indicators.py        RSI, ATR, ADX, Bollinger width
  signals.py           breakout / breakdown / momentum metrics and scores
  picks.py             top-pick gates
  screeners.py         all-time-high screeners
  fundamentals.py      fundamental checks and score
  report.py            HTML report and terminal output
  kite.py              Zerodha Kite Connect client (login, portfolio, GTT)
  calc_page.py         calculator page
  portfolio_page.py    portfolio & GTT page
tests/                 unit tests (no network needed)
```

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```
