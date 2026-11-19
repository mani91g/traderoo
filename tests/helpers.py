"""Synthetic price frames for tests (date x symbol), no network needed."""
import numpy as np
import pandas as pd


def frames(closes: dict, start="2024-01-01", spread=0.01, volume=1_000_000):
    """Build open/high/low/close/volume frames from close paths. Highs and lows sit `spread` around the close."""
    n = max(len(v) for v in closes.values())
    idx = pd.bdate_range(start, periods=n)
    close = pd.DataFrame({s: pd.Series(v, index=idx[-len(v):]) for s, v in closes.items()}, index=idx)
    return {
        "open": close.shift(1).fillna(close),
        "high": close * (1 + spread),
        "low": close * (1 - spread),
        "close": close,
        "volume": close.notna() * float(volume),
    }


def random_walk(n, seed, start=100.0, drift=0.0005, vol=0.015):
    rng = np.random.default_rng(seed)
    return start * np.exp(np.cumsum(rng.normal(drift, vol, n)))
