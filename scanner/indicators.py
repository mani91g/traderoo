"""Vectorised indicators. Every function takes/returns wide frames (date x symbol)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    d = close.diff()
    up = _wilder(d.clip(lower=0), n)
    dn = _wilder(-d.clip(upper=0), n)
    return 100 - 100 / (1 + up / dn)


def true_range(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    pc = close.shift(1)
    tr = np.fmax(high - low, np.fmax((high - pc).abs(), (low - pc).abs()))
    return tr.where(close.notna())


def atr(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    return _wilder(true_range(high, low, close), n)


def adx(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    up = high.diff()
    dn = -low.diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0).where(close.notna())
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0).where(close.notna())
    a = atr(high, low, close, n)
    plus_di = 100 * _wilder(plus_dm, n) / a
    minus_di = 100 * _wilder(minus_dm, n) / a
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return _wilder(dx, n)


def bb_width(close: pd.DataFrame, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """Bollinger band width as a fraction of the middle band."""
    return 2 * k * close.rolling(n).std() / close.rolling(n).mean()
