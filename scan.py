#!/usr/bin/env python3
"""Scan NSE stocks (Nifty 200 plus mid/small caps above a market-cap floor) for
momentum leaders/laggards and breakout/breakdown candidates.

    .venv/bin/python scan.py              # scan, print tables, write reports/
    .venv/bin/python scan.py --open       # ...and open the HTML report
    .venv/bin/python scan.py --asof 2026-10-30   # scan as it looked on a past date
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from scanner import fundamentals, picks, report, screeners, signals
from scanner.data import bse_first_trade, fill_from_nse, load_monthly_highs, load_prices
from scanner.universe import load_kite_tokens, load_universe

ROOT = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=15, help="rows per section (default 15)")
    ap.add_argument("--refresh", action="store_true", help="refetch everything: stock lists, market caps and prices")
    ap.add_argument("--fresh-prices", action="store_true", help="refetch prices only (ignore the 30-minute price cache)")
    ap.add_argument("--universe", choices=["all", "nifty200"], default="all",
                    help="all = every NSE stock above --min-cap plus the Nifty 200 (default); nifty200 = index only")
    ap.add_argument("--min-cap", type=float, default=1000, help="market-cap floor in Rs crore (default 1000)")
    ap.add_argument("--min-turnover", type=float, default=1.0,
                    help="median 20-day traded value floor in Rs crore (default 1)")
    ap.add_argument("--asof", help="YYYY-MM-DD: use data up to and including this date")
    ap.add_argument("--verbose", action="store_true", help="print every section and column in the terminal")
    ap.add_argument("--open", action="store_true", help="open the HTML report when done")
    args = ap.parse_args()

    uni = load_universe(refresh=args.refresh, min_cap_cr=args.min_cap, scope=args.universe)
    uni["kite_token"] = uni.index.map(load_kite_tokens(args.refresh))
    counts = ", ".join(f"{k} {v}" for k, v in uni["segment"].value_counts().items())
    print(f"Universe: {len(uni)} stocks ({counts}). Loading prices...")
    prices = load_prices(list(uni.index), refresh=args.refresh or args.fresh_prices)

    # Fill in any trading day Yahoo has not published yet from NSE's own files.
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    through = pd.Timestamp(now.date()) if (now.hour, now.minute) >= (18, 0) else pd.Timestamp(now.date()) - pd.Timedelta(days=1)
    if args.asof:
        through = min(through, pd.Timestamp(args.asof))
    nse_days = fill_from_nse(prices, through)
    if nse_days:
        print("  Prices for " + ", ".join(f"{d:%a %d %b}" for d in nse_days)
              + " taken from NSE's official end-of-day file (Yahoo has not published them yet).")

    if args.asof:
        cutoff = pd.Timestamp(args.asof)
        for k in ("open", "high", "low", "close", "volume"):
            prices[k] = prices[k].loc[:cutoff]
        if prices.get("index_close") is not None:
            prices["index_close"] = prices["index_close"].loc[:cutoff]
    if len(prices["close"]) < 200:
        print("Not enough price history to scan.", file=sys.stderr)
        return 1

    asof = prices["close"].index[-1]
    warning = ""
    # Weekdays since the latest close that should already have data (holidays aside).
    end = now.date() if (now.hour, now.minute) >= (18, 0) else now.date() - pd.Timedelta(days=1)
    missing_days = int(np.busday_count((asof + pd.Timedelta(days=1)).date(), (pd.Timestamp(end) + pd.Timedelta(days=1)).date()))
    if not args.asof and missing_days > 0:
        warning = (f"Prices are from {asof:%a %d %b}; neither Yahoo nor NSE has published {missing_days} later trading "
                   f"day{'s' if missing_days > 1 else ''} yet (unless {'it was a' if missing_days == 1 else 'they were'} "
                   "market holiday). Run a new scan later.")
    elif asof.date() == now.date() and (now.hour, now.minute) < (15, 35):
        warning = ("Market is still open: today's bar is incomplete, so volume ratios are understated "
                   "and closes may change. Re-run after 15:30 IST for final signals.")

    m = signals.compute(prices, signals.Params(min_turnover_cr=args.min_turnover), groups=uni["industry"])
    m = m.join(uni[["segment", "mcap_cr", "fo"]])
    skipped = sorted(set(uni.index) - set(m.index))
    br = signals.breadth(m)

    index_line = ""
    idx = prices.get("index_close")
    if idx is not None and len(idx) >= 200:
        last = float(idx.iloc[-1])
        s50, s200 = float(idx.tail(50).mean()), float(idx.tail(200).mean())
        index_line = (f"{prices['index_name']} {last:,.0f} "
                      f"({'above' if last > s50 else 'below'} 50-DMA, "
                      f"{'above' if last > s200 else 'below'} 200-DMA)")

    longs, shorts, near = picks.select(m)
    sections = report.build_sections(m, args.top, longs, shorts, picks.LONG_NOTE, picks.SHORT_NOTE, near)

    # All-time-high screeners. These use every stock with today's price, including
    # recent IPOs with too little history for the scan above.
    rules = screeners.ScreenRules(min_cap_cr=args.min_cap)
    monthly = load_monthly_highs(list(uni.index), refresh=args.refresh)
    recent = screeners.recent_listing_symbols(uni, asof, rules.ipo_months)
    scr = screeners.compute(prices, uni, monthly, bse_first_trade(recent), rules)
    pb = screeners.pullbacks(prices, uni, monthly, bse_first_trade(recent), rules)
    sections += report.screen_sections(scr, rules.ipo_months, pb)
    n6 = int((scr["ipo"] & (scr["ipo_months"] <= 6)).sum()) if len(scr) else 0
    print(f"\nData as of {asof:%a %d %b %Y}. {index_line}")
    print(f"Breadth: {br['above_50']:.0f}% above 50-DMA, {br['above_200']:.0f}% above 200-DMA, "
          f"{br['advancers']} up / {br['decliners']} down.")
    if warning:
        print(f"WARNING: {warning}")
    if skipped:
        print(f"Skipped {len(skipped)} stocks (under 200 days of history, no data, or below the turnover floor).")
    # Fundamentals for every stock that appears in any list (cached for a week).
    listed_syms = sorted({sym for sec in sections for sym in sec["df"].index})
    fund = {sym: fundamentals.score(d) for sym, d in fundamentals.fetch(listed_syms).items()}
    strong = sum(1 for f in fund.values() if f["strong"])
    print(f"  Fundamentals: {len(fund)} of {len(listed_syms)} listed stocks have data; {strong} pass as fundamentally strong.")
    report.print_console(sections, verbose=args.verbose)
    print(f"  (screener 2: {n6} of its IPOs listed in the last 6 months)")

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    stem = f"scan_{asof:%Y-%m-%d}"
    full = m.join(uni[["name", "industry", "nifty200"]]).sort_values("rs", ascending=False)
    scr.join(uni[["name", "industry"]]).round(2).to_csv(out_dir / f"{stem}_ath.csv", index_label="symbol")
    pb.join(uni[["name", "industry"]]).round(2).to_csv(out_dir / f"{stem}_ath_pullbacks.csv", index_label="symbol")
    pd.DataFrame([{"symbol": k, "fund_score": v["score"], "strong": v["strong"], "summary": v["summary"],
                   **{name: ("pass" if ok else "fail" if ok is False else "n/a") + f" ({detail})" for name, ok, detail in v["checks"]}}
                  for k, v in fund.items()]).to_csv(out_dir / f"{stem}_fundamentals.csv", index=False)
    full.round(2).to_csv(out_dir / f"{stem}.csv", index_label="symbol")
    html_path = out_dir / f"{stem}.html"
    html_path.write_text(
        report.render_html(sections, uni, prices, br, asof, index_line, warning, skipped,
                           note=(f"Prices for {', '.join(f'{d:%d %b}' for d in nse_days)} are from NSE's official "
                                 "end-of-day file, as Yahoo had not published them yet.") if nse_days else "",
                           fund=fund),
        encoding="utf-8",
    )
    print(f"\nReport: {html_path}\nAll metrics: {out_dir / (stem + '.csv')}")
    if args.open:
        subprocess.run(["open", str(html_path)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
