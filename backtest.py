#!/usr/bin/env python3
"""Replay the scanner over history and measure what happened after each signal.

    .venv/bin/python backtest.py            # 5 years of history
    .venv/bin/python backtest.py --period 10y

Method (event study, no portfolio simulation):
* Every trading day, run the exact scanner logic on data up to that day's close.
* A signal is "entered" at the NEXT day's open and measured at the close 5, 10
  and 20 bars after the signal day.
* "Excess" is the signal's return minus the equal-weight average return of all
  scanned stocks over the same dates, so a rising market does not flatter longs.
* Setups are counted once, on the first day a stock enters the setup state.
  Momentum lists are sampled every 5th day (top N by score).

Known limits: uses TODAY's index members for the whole period (survivorship
bias, which flatters long signals), ignores costs/slippage, and overlapping
holding periods make the t-stats optimistic.
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from scanner import report, signals
from scanner.data import load_prices
from scanner.universe import load_universe

ROOT = Path(__file__).resolve().parent
HORIZONS = (5, 10, 20)
WINDOW = 420        # bars handed to the scanner each day (252 lookback + warm-up)
WARMUP = 260        # first bar index that gets scanned
CONVERT_BARS = 10   # a setup "converts" if it closes through the level within this
# Scanner metrics saved with every signal so filters can be tested afterwards.
FEATURES = ("chg_pct", "rs", "rsi", "adx", "atr_pct", "vol_ratio", "squeeze_pct", "off_52w_high", "off_52w_low",
            "above_200", "close_loc", "ext50_atr", "suspect", "turnover_cr", "grp_rs", "r1m",
            "up_wk_triggered", "down_wk_triggered")


def collect(prices: Dict[str, pd.DataFrame], top: int, groups=None) -> pd.DataFrame:
    close, open_ = prices["close"], prices["open"]
    cols = {s: j for j, s in enumerate(close.columns)}
    c_arr = close.to_numpy()
    entry = open_.shift(-1)
    fwd = {h: (close.shift(-h) / entry - 1) for h in HORIZONS}

    rows: List[dict] = []
    prev_setup = {"up": set(), "down": set()}
    n = len(close)
    for i in range(WARMUP, n):
        sub = {k: prices[k].iloc[i - WINDOW + 1 if i >= WINDOW else 0: i + 1]
               for k in ("open", "high", "low", "close", "volume")}
        m = signals.compute(sub, groups=groups)
        date = close.index[i]
        base = {h: fwd[h].iloc[i][m.index].mean() for h in HORIZONS}
        breadth50 = float(m["above_50"].mean() * 100)  # market regime on the signal day

        def add(sym: str, signal: str, score: float, level: float = np.nan,
                vol_ok: bool = False, converted=np.nan, side: str = "") -> None:
            r = {"date": date, "symbol": sym, "signal": signal, "score": score,
                 "level": level, "vol_ok": vol_ok, "converted": converted, "breadth50": breadth50}
            for f in FEATURES:
                r[f] = m.at[sym, f]
            if side:
                r["tag"] = m.at[sym, f"{side}_tag"]
                r["age"] = m.at[sym, f"{side}_age"]
                r["dist_pct"] = m.at[sym, f"{side}_dist_pct"]
            for h in HORIZONS:
                v = fwd[h].iat[i, cols[sym]]
                r[f"fwd{h}"] = v
                r[f"ex{h}"] = v - base[h]
            rows.append(r)

        for side, name in (("up", "Breakout"), ("down", "Breakdown")):
            st = m[f"{side}_status"]
            for sym in st.index[st == "triggered"]:
                add(sym, name, m.at[sym, f"{side}_score"], m.at[sym, f"{side}_level"],
                    bool(m.at[sym, f"{side}_vol_ok"]), side=side)
            now = set(st.index[st == "setup"])
            for sym in now - prev_setup[side]:
                lvl = m.at[sym, f"{side}_level"]
                nxt = c_arr[i + 1: i + 1 + CONVERT_BARS, cols[sym]]
                conv = np.nan
                if len(nxt) == CONVERT_BARS:
                    conv = bool(np.nanmax(nxt) > lvl) if side == "up" else bool(np.nanmin(nxt) < lvl)
                add(sym, f"{name} setup", m.at[sym, f"{side}_score"], lvl, converted=conv, side=side)
            prev_setup[side] = now

        if (i - WARMUP) % 5 == 0:
            for flag, sc, name in (("leader", "mom_up", "Momentum leader"),
                                   ("laggard", "mom_down", "Momentum laggard")):
                pick = m[m[flag]].sort_values(sc, ascending=False).head(top)
                for sym in pick.index:
                    add(sym, name, pick.at[sym, sc])

        if (i - WARMUP) % 100 == 0:
            print(f"  {date:%Y-%m-%d}  ({i - WARMUP + 1}/{n - WARMUP} days)", flush=True)
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame, label: str) -> dict:
    row = {"Signal": label, "Signals": len(df), "Days": df["date"].nunique()}
    for h in HORIZONS:
        d = df.dropna(subset=[f"fwd{h}"])
        if d.empty:
            continue
        by_day = d.groupby("date")[f"ex{h}"].mean()
        row[f"{h}d ret %"] = d[f"fwd{h}"].mean() * 100
        row[f"{h}d excess %"] = d[f"ex{h}"].mean() * 100
        row[f"{h}d beat mkt %"] = (d[f"ex{h}"] > 0).mean() * 100
        row[f"{h}d t"] = (by_day.mean() / (by_day.std(ddof=1) / np.sqrt(len(by_day)))
                          if len(by_day) > 2 else np.nan)
    if df["converted"].notna().any():
        row[f"Converted in {CONVERT_BARS}d %"] = df["converted"].dropna().astype(float).mean() * 100
    return row


def build_tables(sig: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    order = ["Breakout", "Breakout setup", "Momentum leader",
             "Breakdown", "Breakdown setup", "Momentum laggard"]
    main = [summarise(sig[sig["signal"] == s], s) for s in order if (sig["signal"] == s).any()]

    cuts = []
    for name in ("Breakout", "Breakdown"):
        d = sig[sig["signal"] == name]
        cuts.append(summarise(d[d["vol_ok"]], f"{name}: volume ≥ 2×"))
        cuts.append(summarise(d[~d["vol_ok"]], f"{name}: volume < 2×"))
        for lo, hi in ((0, 60), (60, 75), (75, 101)):
            b = d[(d["score"] >= lo) & (d["score"] < hi)]
            if len(b):
                cuts.append(summarise(b, f"{name}: score {lo}–{min(hi, 100)}"))

    years = []
    for name in order:
        d = sig[sig["signal"] == name]
        for y, g in d.groupby(d["date"].dt.year):
            r = summarise(g, name)
            years.append({"Signal": name, "Year": int(y), "Signals": len(g),
                          "10d ret %": r.get("10d ret %"), "10d excess %": r.get("10d excess %"),
                          "10d beat mkt %": r.get("10d beat mkt %")})
    return {"Overall": pd.DataFrame(main), "Breakouts and breakdowns by volume and score": pd.DataFrame(cuts),
            "By calendar year (10-day horizon)": pd.DataFrame(years)}


def _cell(col: str, v) -> str:
    if isinstance(v, str):
        return f"<td>{html.escape(v)}</td>"
    if v is None or pd.isna(v):
        return "<td>–</td>"
    if col in ("Signals", "Days", "Year"):
        return f"<td>{int(v):,}</td>" if col != "Year" else f"<td>{int(v)}</td>"
    if "ret" in col or "excess" in col:
        cls = "pos" if v > 0 else "neg"
        return f'<td class="{cls}">{v:+.2f}</td>'
    return f"<td>{v:.1f}</td>"


def render(tables: Dict[str, pd.DataFrame], start, end, n_stocks: int) -> str:
    body = ""
    for title, t in tables.items():
        head = "".join(f"<th>{html.escape(c)}</th>" for c in t.columns)
        rows = "".join("<tr>" + "".join(_cell(c, r[c]) for c in t.columns) + "</tr>" for _, r in t.iterrows())
        body += (f'<section><header><h2>{html.escape(title)}</h2></header><div class="scroll">'
                 f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div></section>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Scanner backtest</title>
<style>{report.CSS} td:first-child{{font-weight:600}}</style></head><body><main>
<h1>Scanner backtest</h1>
<p class="sub">Signals from {start:%d %b %Y} to {end:%d %b %Y} · {n_stocks} stocks in today's universe</p>
<p class="warn">Read with care: the universe is today's index members applied to the past (survivorship bias flatters
long signals), costs and slippage are excluded, and overlapping holding periods make t-stats optimistic.</p>
{body}
<footer>Entry at the next day's open after the signal; exit at the close 5/10/20 bars after the signal day.
<b>Excess</b> = return minus the equal-weight average of all scanned stocks over the same dates.
<b>Beat mkt</b> = share of signals with positive excess. <b>t</b> = t-statistic of daily-average excess.
For short-side signals (breakdowns, laggards) a <i>negative</i> excess means the signal worked.
Setups are counted on the first day in the setup state; momentum lists are sampled every 5th day.<br>
Past behaviour of a rule is not a prediction. This is not investment advice.</footer>
</main><script>{report.JS}</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", default="5y", choices=["2y", "5y", "10y"], help="history to replay (default 5y)")
    ap.add_argument("--top", type=int, default=15, help="momentum list size (default 15)")
    ap.add_argument("--universe", choices=["all", "nifty200"], default="all", help="same meaning as in scan.py")
    ap.add_argument("--refresh", action="store_true", help="ignore the price cache")
    args = ap.parse_args()

    uni = load_universe(scope=args.universe)
    print(f"Loading {args.period} of prices for {len(uni)} stocks...")
    prices = load_prices(list(uni.index), refresh=args.refresh, period=args.period)
    if len(prices["close"]) <= WARMUP + max(HORIZONS):
        print("Not enough history.", file=sys.stderr)
        return 1

    print("Replaying scanner day by day...")
    sig = collect(prices, args.top, groups=uni["industry"])
    tables = build_tables(sig)
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.2f}".format)
    for title, t in tables.items():
        print(f"\n== {title} ==\n{t.to_string(index=False)}")

    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    sig.round(4).to_csv(out / "backtest_signals.csv", index=False)
    path = out / "backtest.html"
    path.write_text(render(tables, sig["date"].min(), sig["date"].max(), prices["close"].shape[1]), encoding="utf-8")
    print(f"\nReport: {path}\nEvery signal: {out / 'backtest_signals.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
