"""Two all-time-high screeners.

1. All-time high: market cap of at least Rs 1,000 crore and the latest close
   above the stock's previous all-time high (the highest price traded on any
   earlier day, intraday highs included). A stock that only traded above its
   old high during the day but closed below it does not qualify.
2. Recent IPO at all-time high: the same, limited to companies that listed
   through an IPO in the last 12 months (the report can narrow it to 6).
3. Pullback after an all-time-high breakout: closed above the previous
   all-time high in the last 10 sessions, has since pulled back below its
   newest high, but still closes above the level it broke.

"All-time high" is the highest price the stock has traded at on NSE before the
breakout day: older history comes from monthly bars over the stock's full
Yahoo record, the last two years from daily bars. Prices are adjusted for
splits and dividends.

An IPO is a listing whose first trade on both NSE and BSE was on or within a
week of its NSE listing date. Companies that already traded on BSE (or NSE)
earlier, such as BSE-only companies or SME migrations listing on NSE's main
board, are excluded.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd


@dataclass
class ScreenRules:
    min_cap_cr: float = 1000.0
    min_sessions: int = 5    # trading days needed before an all-time high means anything
    pullback_window: int = 10  # screener 3: breakouts in the last this-many sessions
    ipo_months: int = 12


def compute(prices: Dict[str, pd.DataFrame], uni: pd.DataFrame, monthly_highs: pd.DataFrame,
            bse_first: Dict[str, Optional[str]], r: ScreenRules = ScreenRules()) -> pd.DataFrame:
    """One row per stock whose latest close is above its previous all-time high, with an `ipo` flag."""
    close, high, vol, prior = _prior_highs(prices, monthly_highs)
    broke = close > prior

    today = broke.iloc[-1].fillna(False)
    rows = []
    for s in broke.columns[today.values]:
        c = close[s].dropna()
        if len(c) < r.min_sessions:
            continue
        flags = broke[s].loc[c.index].values[::-1]
        streak = int(np.argmin(flags)) if not flags.all() else len(flags)  # closes above the prior high in a row
        level = float(prior[s].iloc[-1])
        last = float(c.iloc[-1])
        v = vol[s].dropna()
        rows.append({
            "symbol": s,
            "ath_level": level, "ath_wk_level": level,
            "close": last, "chg_pct": (last / float(c.iloc[-2]) - 1) * 100 if len(c) > 1 else np.nan,
            "above_ath_pct": (last / level - 1) * 100,
            "streak": streak,
            "vol_ratio": float(v.iloc[-1] / v.iloc[-21:-1].mean()) if len(v) > 21 else np.nan,
            "turnover_cr": float((c * vol[s].reindex(c.index)).tail(20).median() / 1e7),
            "sessions": len(c),
        })
    if not rows:
        return pd.DataFrame(columns=["ath_level", "close", "ipo", "ipo_months"])
    out = pd.DataFrame(rows).set_index("symbol")
    out["broke"] = out["streak"].map(lambda n: "First close" if n == 1 else f"{n} closes in a row")
    out["ath_vol_ok"] = out["vol_ratio"] >= 2
    out = _tag(out, uni, close, bse_first, r)
    return out.sort_values(["streak", "above_ath_pct"], ascending=[True, True])


def _prior_highs(prices: Dict[str, pd.DataFrame], monthly_highs: pd.DataFrame):
    """(close, high, volume, prior): `prior` is, for each day, the highest price on any earlier day,
    from the daily bars plus monthly bars for history older than the daily window."""
    close, high, vol = prices["close"], prices["high"], prices["volume"]
    syms = [s for s in close.columns if close[s].iloc[-1] == close[s].iloc[-1]]  # has today's close
    close, high, vol = close[syms], high[syms], vol[syms]
    first_day = close.index[0]
    base = monthly_highs.reindex(columns=syms)
    base = base[base.index <= first_day].max()
    # Carry the running high across days with no data, so a missing day never hides it.
    prior = np.fmax(high.cummax().ffill().shift(1), base.reindex(syms).values)
    return close, high, vol, prior


def _tag(out: pd.DataFrame, uni: pd.DataFrame, close: pd.DataFrame,
         bse_first: Dict[str, Optional[str]], r: ScreenRules) -> pd.DataFrame:
    """Apply the market-cap floor and mark recent IPOs."""
    asof = close.index[-1]
    out = out.join(uni[["segment", "mcap_cr", "listed", "nifty200"]], how="left")

    # Market-cap filter. Nifty 200 members are always well above the floor.
    out = out[(out["mcap_cr"] >= r.min_cap_cr) | out["nifty200"].fillna(False).astype(bool)]

    # IPO flag.
    listed = pd.to_datetime(out["listed"])
    recent = listed >= asof - pd.DateOffset(months=r.ipo_months)
    out["ipo_months"] = ((asof - listed).dt.days / 30.44).round(1)
    first_ns = close.apply(lambda col: col.first_valid_index())
    ipo = []
    for s, is_recent in recent.items():
        if not is_recent:
            ipo.append(False)
            continue
        ns_first, bse = first_ns.get(s), bse_first.get(s)
        week_before = listed[s] - pd.Timedelta(days=7)
        earlier = (ns_first is not None and ns_first < week_before) or (bse is not None and pd.Timestamp(bse) < week_before)
        ipo.append(not earlier)
    out["ipo"] = ipo
    out["listed_str"] = listed.dt.strftime("%d %b %Y")
    return out


def pullbacks(prices: Dict[str, pd.DataFrame], uni: pd.DataFrame, monthly_highs: pd.DataFrame,
              bse_first: Dict[str, Optional[str]], r: ScreenRules = ScreenRules()) -> pd.DataFrame:
    """Screener 3: an all-time-high breakout in the last `pullback_window` sessions that has
    since pulled back, but is still closing above the level it broke.

    Stocks closing above their previous all-time high today are left out: they
    are in screener 1. The breakout used is the start of the most recent
    run of closes at new highs.
    """
    close, high, vol, prior = _prior_highs(prices, monthly_highs)
    broke = close > prior
    recent = broke.iloc[-(r.pullback_window + 1):-1]       # earlier sessions in the window, not today
    candidates = recent.columns[recent.any().values & ~broke.iloc[-1].fillna(False).values]
    rows = []
    for s in candidates:
        c = close[s].dropna()
        if len(c) < r.min_sessions:
            continue
        # Start of the most recent breakout run: a stock that closed at new highs several
        # days in a row broke out on the first of those days, above the high before it.
        flags = broke[s].loc[c.index]
        i = flags.index.get_loc(recent[s][recent[s]].index[-1])
        while i > 0 and flags.iloc[i - 1]:
            i -= 1
        when = flags.index[i]
        level = float(prior.at[when, s])
        last = float(c.iloc[-1])
        if not last > level:                               # gave up the breakout
            continue
        peak = float(high[s].loc[when:].max())
        v = vol[s].dropna()
        rows.append({
            "symbol": s, "ath_level": level, "ath_wk_level": level,
            "close": last, "chg_pct": (last / float(c.iloc[-2]) - 1) * 100,
            "broke_on": when, "broke_ago": int((close.index > when).sum()),
            "peak": peak, "off_peak_pct": (last / peak - 1) * 100,
            "above_ath_pct": (last / level - 1) * 100,
            "vol_ratio": float(v.iloc[-1] / v.iloc[-21:-1].mean()) if len(v) > 21 else np.nan,
            "turnover_cr": float((c * vol[s].reindex(c.index)).tail(20).median() / 1e7),
            "sessions": len(c),
        })
    if not rows:
        return pd.DataFrame(columns=["ath_level", "close", "ipo", "ipo_months"])
    out = pd.DataFrame(rows).set_index("symbol")
    out["broke"] = out["broke_on"].dt.strftime("%d %b") + out["broke_ago"].map(lambda n: f" ({n} session{'s' if n > 1 else ''} ago)")
    out["ath_vol_ok"] = out["vol_ratio"] >= 2
    out = _tag(out, uni, close, bse_first, r)
    return out.sort_values("above_ath_pct")   # closest to the breakout level first


def recent_listing_symbols(uni: pd.DataFrame, asof: pd.Timestamp, months: int = 12) -> list:
    listed = pd.to_datetime(uni["listed"])
    return list(uni.index[listed >= asof - pd.DateOffset(months=months)])
