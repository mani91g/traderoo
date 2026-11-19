"""Short lists of the highest-quality long and short candidates.

A pick must pass every gate; the lists are capped at `max_picks` but are never
padded, so on a quiet day they can be short or empty.

Long gates come from the 5-year replay in backtest.py (about 1,330 stocks,
split at 1 Jan 2025). Of the factors tried, two helped in both halves and are
used: a strong industry (median RS of the stock's industry >= 60) and not being
stretched far above the 50-DMA. Close location, weekly confirmation, liquidity
band and RS above 90 did not help consistently and are not gates. The liquidity
floor is there for tradability, not because it improved returns.

The short side has no backtested edge (the same gates worked in the first half
and failed in the second), so its gates are simply strict and it is labelled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import pandas as pd


LONG_NOTE = ("Fresh daily breakouts that pass every gate: score 75+, in a strong industry (industry RS 60+), not more "
             "than 4 ATR above the 50-DMA, at least Rs 5 crore traded daily, clean data. Never padded to 10. "
             "In the backtest such picks beat the average stock by about 1.5% over 20 days, and about half of them beat it.")
SHORT_NOTE = ("Fresh daily breakdowns in F&O stocks with score 75+, RS 30 or lower, below the 200-DMA and volume 1.5x+. "
              "Not validated: in the backtest these gates worked in 2022-24 and failed in 2025-26.")


@dataclass
class PickRules:
    max_picks: int = 10
    # ---- long: a fresh daily breakout that passes all of these
    long_min_score: float = 75.0
    long_min_group_rs: float = 60.0     # median RS of the stock's industry (index members only)
    long_max_ext50_atr: float = 4.0     # ATRs above the 50-DMA; beyond this the move is stretched
    long_min_turnover_cr: float = 5.0   # median daily traded value, Rs crore (tradability, not edge)
    # ---- short: a fresh daily breakdown that passes all of these
    short_min_score: float = 75.0
    short_max_rs: float = 30.0
    short_min_vol_ratio: float = 1.5
    short_fo_only: bool = True          # overnight shorts need stock futures


def select(m: pd.DataFrame, r: PickRules = PickRules()) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (long_picks, short_picks, long_near_misses), each sorted best-first
    with a `why` column. A near miss is a clean breakout with a qualifying score
    that fails exactly one of the remaining long gates; `why` names that gate."""
    clean = ~m["suspect"]

    base = (m["up_status"] == "triggered") & clean & (m["up_score"] >= r.long_min_score)
    gates = pd.DataFrame({
        "industry": m["grp_rs"] >= r.long_min_group_rs,
        "stretch": m["ext50_atr"] < r.long_max_ext50_atr,
        "liquidity": m["turnover_cr"] >= r.long_min_turnover_cr,
    })
    longs = m[base & gates.all(axis=1)].sort_values("up_score", ascending=False).head(r.max_picks).copy()
    longs["why"] = [_why_long(x) for _, x in longs.iterrows()]

    near = m[base & (gates.sum(axis=1) == len(gates.columns) - 1)].sort_values("up_score", ascending=False).copy()
    near["why"] = [_why_missed(x, gates.loc[sym], r) for sym, x in near.iterrows()]

    short_ok = (
        (m["down_status"] == "triggered")
        & clean
        & (m["down_score"] >= r.short_min_score)
        & (m["rs"] <= r.short_max_rs)
        & ~m["above_200"]
        & (m["vol_ratio"] >= r.short_min_vol_ratio)
    )
    if r.short_fo_only:
        short_ok &= m["fo"].fillna(False).astype(bool)
    shorts = m[short_ok].sort_values("down_score", ascending=False).head(r.max_picks).copy()
    shorts["why"] = [_why_short(x) for _, x in shorts.iterrows()]
    return longs, shorts, near


def _why_long(x: pd.Series) -> str:
    bits = [f"{x['vol_ratio']:.1f}× volume", f"RS {x['rs']:.0f}", f"industry RS {x['grp_rs']:.0f}"]
    if x["up_tf"] == "Both":
        bits.append("weekly breakout too")
    if x["up_tag"] == "52W":
        bits.append("52-week high")
    return ", ".join(bits)


def _why_missed(x: pd.Series, passed: pd.Series, r: PickRules) -> str:
    if not passed["industry"]:
        if pd.isna(x["grp_rs"]):
            return "Failed: no industry data (not in an NSE index), so industry strength cannot be checked"
        return f"Failed: industry RS {x['grp_rs']:.0f}, needs {r.long_min_group_rs:.0f}+"
    if not passed["stretch"]:
        return f"Failed: {x['ext50_atr']:.1f} ATR above the 50-DMA, limit is {r.long_max_ext50_atr:.0f}"
    return f"Failed: Rs {x['turnover_cr']:.1f} crore traded daily, needs {r.long_min_turnover_cr:.0f}+"


def _why_short(x: pd.Series) -> str:
    bits = [f"{x['vol_ratio']:.1f}× volume", f"RS {x['rs']:.0f}", "below 200-DMA"]
    if x["down_tf"] == "Both":
        bits.append("weekly breakdown too")
    if x["down_tag"] == "52W":
        bits.append("52-week low")
    return ", ".join(bits)
