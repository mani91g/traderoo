#!/usr/bin/env python3
"""Test stricter breakout filters on the signals recorded by backtest.py.

    .venv/bin/python backtest.py     # first: writes reports/backtest_signals.csv
    .venv/bin/python variants.py

Each variant is a filter on "Breakout" signals (close above the prior 20-day
high, entry next open). To limit data-mining, results are shown separately for
an in-sample period and an out-of-sample period; a variant only "holds" if its
20-day excess return is positive in BOTH with enough signals in each. With ~25
variants tried, one or two can pass by luck alone, so treat passes as
candidates, not proof.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scanner import report

ROOT = Path(__file__).resolve().parent
SIGNALS = ROOT / "reports" / "backtest_signals.csv"
SPLIT = pd.Timestamp("2025-01-01")
MIN_N = 100  # signals needed in each period for a variant to count

VARIANTS = {
    "All breakouts (baseline)": lambda d: d["score"] > -1,
    "Volume ≥ 1.5×": lambda d: d["vol_ratio"] >= 1.5,
    "Volume ≥ 2×": lambda d: d["vol_ratio"] >= 2,
    "Volume ≥ 3×": lambda d: d["vol_ratio"] >= 3,
    "55-day or 52-week high": lambda d: d["tag"].isin(["55D", "52W"]),
    "52-week high": lambda d: d["tag"] == "52W",
    "RS ≥ 80": lambda d: d["rs"] >= 80,
    "RS ≥ 90": lambda d: d["rs"] >= 90,
    "Tight squeeze (≤ 25th pct)": lambda d: d["squeeze_pct"] <= 25,
    "Base ≥ 10 bars": lambda d: d["age"] >= 10,
    "Score ≥ 80": lambda d: d["score"] >= 80,
    "Score ≥ 85": lambda d: d["score"] >= 85,
    "Strong bar (day ≥ +3%)": lambda d: d["chg_pct"] >= 3,
    "Not extended (≤ 2% past level)": lambda d: d["dist_pct"] <= 2,
    "RSI < 70": lambda d: d["rsi"] < 70,
    "Above 200-DMA": lambda d: d["above_200"],
    "Broad market strong (> 60% above 50-DMA)": lambda d: d["breadth50"] > 60,
    "Broad market weak (< 40% above 50-DMA)": lambda d: d["breadth50"] < 40,
    "Volume ≥ 1.5× + RS ≥ 80": lambda d: (d["vol_ratio"] >= 1.5) & (d["rs"] >= 80),
    "Volume ≥ 1.5× + 52-week high": lambda d: (d["vol_ratio"] >= 1.5) & (d["tag"] == "52W"),
    "Volume ≥ 2× + strong bar": lambda d: (d["vol_ratio"] >= 2) & (d["chg_pct"] >= 3),
    "Volume ≥ 1.5× + tight squeeze": lambda d: (d["vol_ratio"] >= 1.5) & (d["squeeze_pct"] <= 25),
    "RS ≥ 80 + 52-week high": lambda d: (d["rs"] >= 80) & (d["tag"] == "52W"),
    "RS ≥ 80 + market strong": lambda d: (d["rs"] >= 80) & (d["breadth50"] > 60),
    "RS ≥ 80 + 52W high + volume ≥ 1.5×": lambda d: (d["rs"] >= 80) & (d["tag"] == "52W") & (d["vol_ratio"] >= 1.5),
    "RS ≥ 80 + base ≥ 10 + volume ≥ 1.5×": lambda d: (d["rs"] >= 80) & (d["age"] >= 10) & (d["vol_ratio"] >= 1.5),
}


def stats(d: pd.DataFrame, prefix: str) -> dict:
    out = {f"{prefix} N": len(d)}
    for h in (10, 20):
        x = d.dropna(subset=[f"ex{h}"])
        by_day = x.groupby("date")[f"ex{h}"].mean()
        out[f"{prefix} {h}d excess %"] = x[f"ex{h}"].mean() * 100 if len(x) else np.nan
        if h == 20:
            out[f"{prefix} 20d beat %"] = (x["ex20"] > 0).mean() * 100 if len(x) else np.nan
            out[f"{prefix} 20d t"] = (by_day.mean() / (by_day.std(ddof=1) / np.sqrt(len(by_day)))
                                      if len(by_day) > 2 else np.nan)
    return out


def main() -> int:
    if not SIGNALS.exists():
        print("Run backtest.py first.", file=sys.stderr)
        return 1
    sig = pd.read_csv(SIGNALS, parse_dates=["date"])
    if "vol_ratio" not in sig.columns:
        print("backtest_signals.csv is from an older run; re-run backtest.py.", file=sys.stderr)
        return 1
    bo = sig[sig["signal"] == "Breakout"].copy()
    bo["above_200"] = bo["above_200"].astype(bool)
    ins, oos = bo[bo["date"] < SPLIT], bo[bo["date"] >= SPLIT]

    rows = []
    for name, f in VARIANTS.items():
        r = {"Variant": name, **stats(ins[f(ins)], "IS"), **stats(oos[f(oos)], "OOS")}
        r["Holds"] = ("yes" if r["IS N"] >= MIN_N and r["OOS N"] >= MIN_N
                      and r["IS 20d excess %"] > 0 and r["OOS 20d excess %"] > 0
                      else "thin" if min(r["IS N"], r["OOS N"]) < MIN_N else "no")
        rows.append(r)
    t = pd.DataFrame(rows)

    span = f"IS = {ins['date'].min():%b %Y}–{ins['date'].max():%b %Y}, OOS = {oos['date'].min():%b %Y}–{oos['date'].max():%b %Y}"
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.float_format", "{:.2f}".format)
    print(span)
    print(t.to_string(index=False))

    def cell(c, v):
        if isinstance(v, str):
            cls = ' class="pos"' if v == "yes" else ""
            return f"<td{cls}>{html.escape(v)}</td>"
        if pd.isna(v):
            return "<td>–</td>"
        if c.endswith(" N"):
            return f"<td>{int(v):,}</td>"
        if "excess" in c:
            return f'<td class="{"pos" if v > 0 else "neg"}">{v:+.2f}</td>'
        return f"<td>{v:.1f}</td>"

    head = "".join(f"<th>{html.escape(c)}</th>" for c in t.columns)
    body = "".join("<tr>" + "".join(cell(c, r[c]) for c in t.columns) + "</tr>" for _, r in t.iterrows())
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Breakout variants</title>
<style>{report.CSS} td:first-child{{font-weight:600}}</style></head><body><main>
<h1>Breakout variants</h1><p class="sub">{html.escape(span)}</p>
<p class="warn">{len(VARIANTS)} filters were tried on the same history, so one or two can look good by chance.
Today's index members are applied to the past (survivorship bias) and costs are excluded.</p>
<section><div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></section>
<footer>Excess = return from next-day open to the close 10/20 bars after the signal, minus the equal-weight average of all
scanned stocks over the same dates. <b>Holds</b> = positive 20-day excess in both periods with at least {MIN_N} signals in each;
"thin" = too few signals to judge. Not investment advice.</footer>
</main><script>{report.JS}</script></body></html>"""
    out = ROOT / "reports" / "variants.html"
    out.write_text(page, encoding="utf-8")
    print(f"\nReport: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
