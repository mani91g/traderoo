"""Daily OHLCV for the universe via Yahoo Finance, with a short-lived local cache."""
from __future__ import annotations

import pickle
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional

warnings.filterwarnings("ignore", message=".*OpenSSL.*")

import pandas as pd  # noqa: E402
import yfinance as yf  # noqa: E402

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE_TTL_SEC = 30 * 60
INDEX_TICKERS = {"^CRSLDX": "Nifty 500", "^CNX200": "Nifty 200", "^NSEI": "Nifty 50"}  # first that works
CHUNK = 250  # tickers per Yahoo request
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def _fetch(symbols: List[str], period: str) -> Dict[str, pd.DataFrame]:
    tickers = [f"{s}.NS" for s in symbols]
    parts = []
    for i in range(0, len(tickers), CHUNK):
        part = yf.download(
            tickers[i:i + CHUNK],
            period=period,
            interval="1d",
            auto_adjust=True,  # adjust for splits/dividends so levels are comparable
            group_by="column",
            threads=True,
            progress=False,
        )
        if not part.empty:
            parts.append(part)
        if len(tickers) > CHUNK:
            print(f"  prices: {min(i + CHUNK, len(tickers))}/{len(tickers)}", flush=True)
    if not parts:
        raise RuntimeError("Yahoo Finance returned no data")
    raw = pd.concat(parts, axis=1)
    out = {}
    for f in FIELDS:
        wide = raw[f].copy()
        wide.columns = [c[:-3] for c in wide.columns]  # strip ".NS"
        wide.index = pd.to_datetime(wide.index).tz_localize(None)
        out[f.lower()] = wide.dropna(how="all").sort_index()
    # Yahoo sometimes returns a day with volume but no prices yet (a session it
    # has not finished publishing). Keep only days that have prices, in every field.
    days = out["close"].index
    for k in ("open", "high", "low", "volume"):
        out[k] = out[k].reindex(days)

    out["index_close"] = None
    out["index_name"] = None
    for t in INDEX_TICKERS:
        try:
            idx = yf.download(t, period=period, interval="1d", auto_adjust=True,
                              progress=False)["Close"].squeeze().dropna()
            if len(idx) > 200:
                idx.index = pd.to_datetime(idx.index).tz_localize(None)
                out["index_close"] = idx
                out["index_name"] = INDEX_TICKERS[t]
                break
        except Exception:
            continue
    return out


def load_prices(
    symbols: List[str], refresh: bool = False, period: str = "2y"
) -> Dict[str, Optional[pd.DataFrame]]:
    """Wide frames (date x symbol) keyed open/high/low/close/volume, plus index_close."""
    CACHE_PATH = CACHE_DIR / f"prices_{period}.pkl"
    if (
        not refresh
        and CACHE_PATH.exists()
        and time.time() - CACHE_PATH.stat().st_mtime < CACHE_TTL_SEC
    ):
        with CACHE_PATH.open("rb") as fh:
            cached = pickle.load(fh)
        if set(symbols) <= set(cached["close"].columns):
            return cached

    data = _fetch(symbols, period)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("wb") as fh:
        pickle.dump(data, fh)
    return data


# --------------------------------------------------------- all-time highs --

ATH_CACHE = CACHE_DIR / "ath_monthly.pkl"
ATH_TTL_SEC = 7 * 86400


def load_monthly_highs(symbols: List[str], refresh: bool = False) -> pd.DataFrame:
    """Monthly highs over each stock's full Yahoo history (month x symbol), cached weekly.

    The daily data only covers two years; these monthly bars supply the part of
    the all-time high that is older than that.
    """
    if not refresh and ATH_CACHE.exists() and time.time() - ATH_CACHE.stat().st_mtime < ATH_TTL_SEC:
        with ATH_CACHE.open("rb") as fh:
            cached = pickle.load(fh)
        missing = [s for s in symbols if s not in cached.columns]
        if not missing:
            return cached
    else:
        cached, missing = pd.DataFrame(), list(symbols)

    print(f"  Fetching full price history for {len(missing)} stocks (weekly refresh)...", flush=True)
    parts = []
    tickers = [f"{s}.NS" for s in missing]
    for i in range(0, len(tickers), CHUNK):
        part = yf.download(tickers[i:i + CHUNK], period="max", interval="1mo", auto_adjust=True,
                           group_by="column", threads=True, progress=False)
        if not part.empty:
            hi = part["High"].copy()
            if isinstance(hi, pd.Series):  # a single ticker comes back as a Series
                hi = hi.to_frame(tickers[i])
            hi.columns = [c[:-3] for c in hi.columns]
            hi.index = pd.to_datetime(hi.index).tz_localize(None)
            parts.append(hi)
    fresh = pd.concat(parts, axis=1) if parts else pd.DataFrame()
    for s in missing:  # remember symbols with no history so they are not refetched every run
        if s not in fresh.columns:
            fresh[s] = float("nan")
    out = pd.concat([cached, fresh], axis=1) if not cached.empty else fresh
    out = out.loc[:, ~out.columns.duplicated(keep="last")].sort_index()
    ATH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with ATH_CACHE.open("wb") as fh:
        pickle.dump(out, fh)
    return out


BSE_FIRST = CACHE_DIR / "bse_first_trade.json"


def bse_first_trade(symbols: List[str]) -> Dict[str, Optional[str]]:
    """Date of the first BSE trade within the last two years per symbol (None if none).

    Used to tell an IPO (first trades on BSE and NSE on the same day) from a
    company that was already listed on BSE and has now listed on NSE too.
    Results never change once known, so they are cached for good.
    """
    import json
    known: Dict[str, Optional[str]] = json.loads(BSE_FIRST.read_text()) if BSE_FIRST.exists() else {}
    missing = [s for s in symbols if s not in known]
    if missing:
        print(f"  Checking BSE history for {len(missing)} recent listings...", flush=True)
        for i in range(0, len(missing), CHUNK):
            batch = missing[i:i + CHUNK]
            try:
                d = yf.download([f"{s}.BO" for s in batch], period="2y", interval="1d", auto_adjust=True,
                                group_by="column", threads=True, progress=False)["Close"]
                if isinstance(d, pd.Series):
                    d = d.to_frame(f"{batch[0]}.BO")
            except Exception:
                continue  # leave unknown; retried next run
            for s in batch:
                col = d.get(f"{s}.BO")
                first = col.dropna().index[0] if col is not None and col.notna().any() else None
                known[s] = pd.Timestamp(first).strftime("%Y-%m-%d") if first is not None else None
        BSE_FIRST.parent.mkdir(parents=True, exist_ok=True)
        BSE_FIRST.write_text(json.dumps(known))
    return {s: known.get(s) for s in symbols}


# ------------------------------------------------- NSE end-of-day fallback --

NSE_EOD_DIR = CACHE_DIR / "nse_eod"
NSE_ARCHIVE = "https://nsearchives.nseindia.com/content"
NSE_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept": "*/*"}
INDEX_NAMES = {"Nifty 500": "Nifty 500", "Nifty 200": "Nifty 200", "Nifty 50": "Nifty 50"}


def _nse_get(url: str, path: Path) -> Optional[bytes]:
    """Download an NSE archive file once and keep it. None if NSE has no file for that day."""
    import urllib.error
    import urllib.request
    if path.exists():
        return path.read_bytes()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=NSE_HEADERS), timeout=60) as resp:
            body = resp.read()
    except (urllib.error.URLError, OSError):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return body


def nse_day(day: pd.Timestamp) -> Optional[pd.DataFrame]:
    """NSE's official end-of-day prices (the "bhavcopy") for one day, indexed by
    symbol, or None if there is no file (a holiday, or not published yet)."""
    import io
    import zipfile
    name = f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
    body = _nse_get(f"{NSE_ARCHIVE}/cm/{name}", NSE_EOD_DIR / name)
    if not body:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            df = pd.read_csv(z.open(z.namelist()[0]))
    except (zipfile.BadZipFile, ValueError, KeyError):
        (NSE_EOD_DIR / name).unlink(missing_ok=True)  # an error page, not the file: retry next time
        return None
    df = df[df["SctySrs"].isin(["EQ", "BE", "BZ"])]
    df = df.sort_values("SctySrs").drop_duplicates("TckrSymb")  # EQ first if listed twice
    return df.set_index("TckrSymb").rename(columns={"OpnPric": "open", "HghPric": "high", "LwPric": "low",
                                                    "ClsPric": "close", "TtlTradgVol": "volume"})[
        ["open", "high", "low", "close", "volume"]]


def nse_index_close(day: pd.Timestamp, name: str) -> Optional[float]:
    fname = f"ind_close_all_{day:%d%m%Y}.csv"
    body = _nse_get(f"{NSE_ARCHIVE}/indices/{fname}", NSE_EOD_DIR / fname)
    if not body or not body.startswith(b"Index Name"):
        (NSE_EOD_DIR / fname).unlink(missing_ok=True)
        return None
    import io
    df = pd.read_csv(io.BytesIO(body))
    row = df[df["Index Name"].str.strip().str.lower() == name.lower()]
    return float(row["Closing Index Value"].iloc[0]) if len(row) else None


def fill_from_nse(prices: Dict[str, Optional[pd.DataFrame]], through: pd.Timestamp) -> List[pd.Timestamp]:
    """Add trading days that Yahoo has not published yet, or published only for
    some stocks, from NSE's official end-of-day files, up to and including
    `through`. Returns the days filled.

    NSE's prices are as traded (not adjusted). That matches Yahoo's for recent
    days except on a split or bonus date, which the scanner's data checks flag.
    """
    close = prices["close"]
    added = []
    # Recent days Yahoo published only partly (most stocks missing): fill the gaps from NSE.
    counts = close.notna().sum(axis=1)
    typical = counts.tail(30).median()
    for day in close.index[-10:]:
        if counts[day] < 0.8 * typical and day <= through:
            eod = nse_day(day)
            if eod is None:
                continue
            for k in ("open", "high", "low", "close", "volume"):
                frame = prices[k]
                frame.loc[day] = frame.loc[day].fillna(eod[k].reindex(frame.columns))
            added.append(day)
    last = prices["close"].index[-1]
    for day in pd.bdate_range(last + pd.Timedelta(days=1), through):
        eod = nse_day(day)
        if eod is None:
            continue  # holiday or not yet published
        for k in ("open", "high", "low", "close", "volume"):
            prices[k].loc[day] = eod[k].reindex(prices[k].columns)
        idx = prices.get("index_close")
        if idx is not None and prices.get("index_name"):
            v = nse_index_close(day, prices["index_name"])
            if v is not None:
                idx.loc[day] = v
        added.append(day)
    return added
