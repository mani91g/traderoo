import numpy as np
import pandas as pd

from scanner import screeners
from tests.helpers import frames


def universe(symbols, cap=5000.0):
    return pd.DataFrame({"segment": "Other", "mcap_cr": cap, "listed": pd.Timestamp("2000-01-01"),
                         "nifty200": False}, index=symbols)


def no_history(prices):
    return pd.DataFrame(columns=prices["close"].columns, index=pd.DatetimeIndex([]), dtype=float)


def test_close_above_previous_high_is_listed():
    base = [100.0] * 30
    p = frames({"UP": base + [110.0], "FLAT": base + [100.0]})
    out = screeners.compute(p, universe(["UP", "FLAT"]), no_history(p), {})
    assert list(out.index) == ["UP"]
    assert out.loc["UP", "streak"] == 1


def test_intraday_only_high_is_not_listed():
    base = [100.0] * 30
    p = frames({"TOUCH": base + [100.5]})
    p["high"].iloc[-1, 0] = 106.0          # traded above the old high (101) but closed below it
    out = screeners.compute(p, universe(["TOUCH"]), no_history(p), {})
    assert out.empty


def test_older_monthly_high_blocks_a_false_breakout():
    p = frames({"OLD": [100.0] * 30 + [110.0]})
    monthly = pd.DataFrame({"OLD": [150.0]}, index=[pd.Timestamp("2020-01-01")])
    assert screeners.compute(p, universe(["OLD"]), monthly, {}).empty


def test_market_cap_floor():
    p = frames({"SMALL": [100.0] * 30 + [110.0]})
    assert screeners.compute(p, universe(["SMALL"], cap=500.0), no_history(p), {}).empty


def test_pullback_holding_above_breakout_level():
    path = [100.0] * 30 + [110.0, 115.0, 105.0]   # broke 101, peaked, pulled back but still above 101
    p = frames({"PB": path, "LOST": [100.0] * 30 + [110.0, 115.0, 99.0]})
    out = screeners.pullbacks(p, universe(["PB", "LOST"]), no_history(p), {})
    assert list(out.index) == ["PB"]
    assert np.isclose(out.loc["PB", "ath_level"], 101.0)


def test_ipo_flag_needs_no_earlier_trading():
    p = frames({"NEW": [100.0] * 8 + [110.0]}, start="2026-10-01")
    uni = universe(["NEW"])
    uni["listed"] = p["close"].index[0]
    fresh = screeners.compute(p, uni, no_history(p), {"NEW": None})
    moved = screeners.compute(p, uni, no_history(p), {"NEW": "2025-01-01"})   # traded on BSE long before
    assert bool(fresh.loc["NEW", "ipo"]) and not bool(moved.loc["NEW", "ipo"])


def test_a_missing_day_does_not_hide_the_running_high():
    p = frames({"GAP": [50.0] * 20 + [100.0] * 10 + [99.0, 99.5]})
    for k in ("open", "high", "low", "close", "volume"):
        p[k].iloc[-2] = float("nan")                      # a day with no data before today
    monthly = pd.DataFrame({"GAP": [40.0]}, index=[pd.Timestamp("2020-01-01")])
    assert screeners.compute(p, universe(["GAP"]), monthly, {}).empty   # 99.5 is below the 101 high
