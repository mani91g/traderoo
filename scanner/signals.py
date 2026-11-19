"""Turn price history into one row of metrics, setups and scores per stock.

Three ideas are scored, each 0-100:

* momentum   - relative strength vs the rest of the scanned universe, trend alignment,
               proximity to the 52-week extreme, trend strength (ADX).
* breakout   - price at/through a prior N-day high after a base, scored on
               volume surge, relative strength, thrust, market breadth and trend
               (weights informed by backtest.py).
* breakdown  - price at/through a prior N-day low, scored descriptively on
               proximity, contraction, trend, weakness and volume.

"Triggered" means today's close is through the level; "setup" means price is
coiled within `setup_max_atr` ATRs of the level but has not closed through it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd

from . import indicators as ind


@dataclass
class Params:
    min_bars: int = 200          # history needed for a stock to be scanned
    min_turnover_cr: float = 1.0 # median 20-day traded value (Rs crore) needed to be scanned
    pivot_window: int = 20       # the level is the prior N-day high / low
    min_base_bars: int = 3       # level must be at least this many bars old
    setup_max_atr: float = 1.5   # "near the level" = within this many ATRs
    squeeze_lookback: int = 126  # BB-width percentile window
    vol_surge: float = 2.0       # volume / 20d average that counts as confirmation
    weekly_window: int = 20      # weekly level is the prior N-week high / low
    weekly_min_base: int = 2     # weekly level must be at least this many weeks old
    leader_min_rs: int = 70
    laggard_max_rs: int = 30


def _clip01(x):
    return np.clip(x, 0.0, 1.0)


def weekly_bars(prices: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Resample daily wide frames to weeks ending Friday. The last bar is the
    week to date when the latest session is not a Friday."""
    how = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = {k: prices[k].resample("W-FRI").agg(f) for k, f in how.items() if k in prices}
    live = out["close"].notna().any(axis=1)
    weeks = live.index[live.values]
    return {k: v.reindex(weeks) for k, v in out.items()}


def compute(prices: Dict[str, pd.DataFrame], p: Params = Params(),
            groups: Optional[pd.Series] = None) -> pd.DataFrame:
    """`groups` optionally maps symbol -> industry, used for the industry-strength factor."""
    close, high, low, vol = (prices[k] for k in ("close", "high", "low", "volume"))

    enough = close.notna().sum() >= p.min_bars
    has_last = close.iloc[-1].notna()
    # Liquidity floor: thinly traded small caps produce breakouts nobody can trade.
    turnover = (close * vol).rolling(20).median().iloc[-1] / 1e7
    keep = close.columns[enough & has_last & (turnover >= p.min_turnover_cr)]
    close, high, low, vol = close[keep], high[keep], low[keep], vol[keep]

    last = lambda df: df.iloc[-1]  # noqa: E731
    prev = lambda df: df.iloc[-2]  # noqa: E731

    sma20 = last(close.rolling(20).mean())
    sma50 = last(close.rolling(50).mean())
    sma200 = last(close.rolling(200).mean())
    atr = last(ind.atr(high, low, close))
    c = last(close)

    m = pd.DataFrame(index=keep)
    m["close"] = c
    m["turnover_cr"] = turnover[keep]
    m["chg_pct"] = (c / prev(close) - 1) * 100
    m["rsi"] = last(ind.rsi(close))
    m["adx"] = last(ind.adx(high, low, close))
    m["atr_pct"] = atr / c * 100
    for label, n in (("r1m", 21), ("r3m", 63), ("r6m", 126), ("r9m", 189), ("r12m", 252)):
        m[label] = (c / close.shift(n).iloc[-1] - 1) * 100

    # Relative strength rating: percentile of a recency-weighted return within
    # the universe (1 = weakest, 99 = strongest). Missing long lookbacks are
    # skipped and the remaining weights renormalised.
    w = pd.Series({"r3m": 0.4, "r6m": 0.2, "r9m": 0.2, "r12m": 0.2})
    rets = m[w.index]
    blended = (rets * w).sum(axis=1) / (rets.notna() * w).sum(axis=1)
    m["rs"] = (blended.rank(pct=True) * 98 + 1).round()

    hi52 = last(high.rolling(252, min_periods=120).max())
    lo52 = last(low.rolling(252, min_periods=120).min())
    m["off_52w_high"] = (c / hi52 - 1) * 100
    m["off_52w_low"] = (c / lo52 - 1) * 100
    m["above_50"] = c > sma50
    m["above_200"] = c > sma200

    # Volume: today vs the prior 20-day average, and up-day vs down-day volume.
    m["vol_ratio"] = last(vol) / prev(vol.rolling(20).mean())

    # Refinement factors (tested in backtest.py before being used for picks).
    rng = last(high) - last(low)
    m["close_loc"] = ((c - last(low)) / rng.replace(0, np.nan)).fillna(0.5)  # 1 = closed at the day's high
    m["ext50_atr"] = (c - sma50) / atr                                       # stretch above/below the 50-DMA
    # Data that cannot be trusted: an impossible volume spike (a hole in the
    # volume history) or a one-day move beyond 35% (usually an unadjusted split).
    big_move = close.pct_change(fill_method=None).tail(126).abs().max() > 0.35
    m["suspect"] = (m["vol_ratio"] > 25) | big_move
    d = close.diff()
    up_v = last(vol.where(d > 0, 0.0).rolling(20).sum())
    dn_v = last(vol.where(d < 0, 0.0).rolling(20).sum())
    m["updown_vol"] = up_v / dn_v.replace(0, np.nan)

    # Volatility contraction, measured the day before so a breakout bar does
    # not erase the squeeze that preceded it. Low percentile = tight.
    bbw_pct = ind.bb_width(close).rolling(p.squeeze_lookback).rank(pct=True)
    m["squeeze_pct"] = prev(bbw_pct) * 100
    tight = 1 - m["squeeze_pct"] / 100

    # ---- Momentum -------------------------------------------------------
    stack_up = ((c > sma20).astype(int) + (sma20 > sma50) + (sma50 > sma200)) / 3
    stack_dn = ((c < sma20).astype(int) + (sma20 < sma50) + (sma50 < sma200)) / 3
    adx_s = _clip01((m["adx"] - 15) / 25)
    m["mom_up"] = 100 * (
        0.50 * m["rs"] / 100
        + 0.20 * stack_up
        + 0.20 * _clip01(1 + m["off_52w_high"] / 25)
        + 0.10 * adx_s
    )
    m["mom_down"] = 100 * (
        0.50 * (100 - m["rs"]) / 100
        + 0.20 * stack_dn
        + 0.20 * _clip01(1 - m["off_52w_low"] / 25)
        + 0.10 * adx_s
    )
    # Industry strength: median RS of the stock's industry (needs 5+ members).
    m["grp_rs"] = np.nan
    if groups is not None:
        g = groups.reindex(keep).replace("", np.nan)
        med = m["rs"].groupby(g).transform("median")
        size = m["rs"].groupby(g).transform("size")
        m["grp_rs"] = med.where(size >= 5)
    m["leader"] = m["above_50"] & m["above_200"] & (m["rs"] >= p.leader_min_rs)
    m["laggard"] = ~m["above_50"] & ~m["above_200"] & (m["rs"] <= p.laggard_max_rs)

    # ---- Breakout / breakdown ------------------------------------------
    n = p.pivot_window
    for side in ("up", "down"):
        src, agg, arg = (high, "max", np.nanargmax) if side == "up" else (low, "min", np.nanargmin)
        # Extreme of the prior k bars, excluding today.
        px = lambda df, k: getattr(df.rolling(k, min_periods=min(k, 120)), agg)().shift(1).iloc[-1]  # noqa: E731

        level = px(src, n)
        l55, l252 = px(src, 55), px(src, 252)
        same = lambda a, b: (a - b).abs() <= 1e-9 * b  # noqa: E731
        tag = pd.Series("20D", index=keep)
        tag[same(level, l55)] = "55D"
        tag[same(level, l252)] = "52W"
        tag_pts = tag.map({"20D": 0.3, "55D": 0.6, "52W": 1.0})

        # Bars since the level was set (1 = yesterday). A level set yesterday
        # is a running trend, not a base.
        window = src.iloc[-(n + 1):-1].to_numpy()
        age = pd.Series(n - arg(window, axis=0), index=keep)

        sign = 1 if side == "up" else -1
        gap_atr = sign * (level - c) / atr          # >0: not yet through the level
        dist_pct = (c / level - 1) * 100
        triggered = (gap_atr < 0) & (age >= p.min_base_bars)
        setup = (gap_atr >= 0) & (gap_atr <= p.setup_max_atr) & (age >= p.min_base_bars)
        if side == "up":
            setup &= m["above_50"]
            trend = (m["above_50"].astype(int) + m["above_200"] + (sma50 > sma200)) / 3
            rs_s = m["rs"] / 100
            flow = _clip01((m["updown_vol"] - 0.7) / 0.8)
        else:
            setup &= ~m["above_50"]
            trend = ((~m["above_50"]).astype(int) + ~m["above_200"] + (sma50 < sma200)) / 3
            rs_s = (100 - m["rs"]) / 100
            flow = _clip01((1 / m["updown_vol"] - 0.7) / 0.8)

        proximity = pd.Series(np.where(triggered, 1.0, _clip01(1 - gap_atr / p.setup_max_atr)), index=keep)
        volume = pd.Series(np.where(triggered, _clip01(m["vol_ratio"] / 2), flow), index=keep).fillna(0)
        if side == "up":
            # Weights chosen from the Nov 2022 - Dec 2024 backtest (see README):
            # heavy volume, relative strength, a decisive close through the
            # level and a healthy broad market preceded the better breakouts;
            # squeeze, base length and level type did not, so they are unscored.
            market = float(_clip01((m["above_50"].mean() * 100 - 40) / 20))
            surge = _clip01((m["vol_ratio"].fillna(0) - 1) / 2)   # 1x -> 0, 3x -> 1
            thrust = _clip01(-gap_atr)                            # ATRs closed past the level
            trig = 0.35 * surge + 0.30 * rs_s + 0.15 * thrust + 0.10 * market + 0.10 * trend
            pre = 0.30 * proximity + 0.35 * rs_s + 0.15 * trend + 0.10 * market + 0.10 * volume
            score = 100 * pd.Series(np.where(triggered, trig, pre), index=keep)
        else:
            # No breakdown filter held up in the backtest, so this side keeps
            # the original descriptive weighting.
            score = 100 * (
                0.30 * proximity
                + 0.20 * tight.fillna(0)
                + 0.15 * trend
                + 0.15 * rs_s
                + 0.10 * volume
                + 0.10 * tag_pts
            )
        status = pd.Series("", index=keep)
        status[setup] = "setup"
        status[triggered] = "triggered"

        m[f"{side}_level"] = level
        m[f"{side}_tag"] = tag
        m[f"{side}_age"] = age
        m[f"{side}_dist_pct"] = dist_pct
        m[f"{side}_status"] = status
        m[f"{side}_score"] = score.where(status != "")
        m[f"{side}_vol_ok"] = triggered & (m["vol_ratio"] >= p.vol_surge)

    # ---- Weekly timeframe ----------------------------------------------
    # Same idea on weekly bars: the latest weekly close (week to date) is
    # through the prior N-week high/low, and that level is at least
    # `weekly_min_base` weeks old, so the break happened this week.
    wk = weekly_bars({"high": high, "low": low, "close": close, "volume": vol})
    wc = wk["close"].iloc[-1]
    nw = p.weekly_window
    sessions = int((close.index > wk["close"].index[-2]).sum())  # days in the current week
    m["wk_chg_pct"] = (wc / wk["close"].iloc[-2] - 1) * 100
    m["wk_vol_ratio"] = wk["volume"].iloc[-1] / (wk["volume"].iloc[-11:-1].mean() * sessions / 5)
    for side in ("up", "down"):
        src, agg, arg, fill = ((wk["high"], "max", np.argmax, -np.inf) if side == "up"
                               else (wk["low"], "min", np.argmin, np.inf))
        wlevel = getattr(src.rolling(nw, min_periods=nw // 2), agg)().shift(1).iloc[-1]
        window = src.iloc[-(nw + 1):-1].fillna(fill).to_numpy()
        wage = pd.Series(len(window) - arg(window, axis=0), index=keep)
        through = (wc > wlevel) if side == "up" else (wc < wlevel)
        wtrig = through & (wage >= p.weekly_min_base)
        daily = m[f"{side}_status"] == "triggered"
        m[f"{side}_wk_level"] = wlevel
        m[f"{side}_wk_dist_pct"] = (wc / wlevel - 1) * 100
        m[f"{side}_wk_age"] = wage
        m[f"{side}_wk_triggered"] = wtrig
        m[f"{side}_tf"] = np.select([daily & wtrig, daily, wtrig], ["Both", "Daily", "Weekly"], default="")
        m[f"{side}_tf_rank"] = m[f"{side}_tf"].map({"Both": 0, "Daily": 1, "Weekly": 2, "": 3})

    return m


def breadth(m: pd.DataFrame) -> Dict[str, float]:
    return {
        "n": len(m),
        "above_50": float(m["above_50"].mean() * 100),
        "above_200": float(m["above_200"].mean() * 100),
        "advancers": int((m["chg_pct"] > 0).sum()),
        "decliners": int((m["chg_pct"] < 0).sum()),
        "near_high": int((m["off_52w_high"] >= -2).sum()),
        "near_low": int((m["off_52w_low"] <= 2).sum()),
    }
