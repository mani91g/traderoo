"""Scan universe: NSE-listed equities above a market-cap floor, tagged by cap segment.

Sources (all cached under data/ and refreshed weekly):
* NSE's list of listed equities (EQ series only; trade-to-trade series are excluded).
* NSE index constituent files, used for the cap segment and industry of each stock.
* Market capitalisation from Yahoo Finance.
"""
from __future__ import annotations

import json
import time
import urllib.request
import warnings
from pathlib import Path
from typing import Dict

warnings.filterwarnings("ignore", message=".*OpenSSL.*")

import pandas as pd  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LIST_DIR = DATA_DIR / "lists"
MCAP_PATH = DATA_DIR / "marketcap.csv"
MCAP_META = DATA_DIR / "marketcap.json"
SCREEN_FLOOR_CR = 500.0  # caps are fetched down to this level so --min-cap can vary
MAX_AGE_DAYS = 7
NSE = "https://nsearchives.nseindia.com/content"
EQUITY_URL = f"{NSE}/equities/EQUITY_L.csv"
FO_URL = f"{NSE}/fo/fo_mktlots.csv"  # stocks with futures & options (the only ones shortable overnight)
# Cap segment by index membership. Order matters: first match wins.
SEGMENTS = {
    "Large": "ind_nifty100list",
    "Mid": "ind_niftymidcap150list",
    "Small": "ind_niftysmallcap250list",
    "Micro": "ind_niftymicrocap250_list",
}
NIFTY200 = "ind_nifty200list"
OTHER = "Other"  # above the cap floor but in none of the indices above
CRORE = 1e7


def _stale(path: Path) -> bool:
    return not path.exists() or time.time() - path.stat().st_mtime > MAX_AGE_DAYS * 86400


def _get(url: str, path: Path, refresh: bool) -> Path:
    """Download `url` to `path` if missing/stale; keep the cached copy on failure."""
    if not (refresh or _stale(path)):
        return path
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "text/csv,*/*",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
        if b"ymbol" not in body[:300] and b"SYMBOL" not in body[:300]:
            raise ValueError("response did not look like an NSE CSV")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    except Exception as exc:
        if not path.exists():
            raise RuntimeError(f"Could not fetch {url}: {exc}") from exc
        print(f"  (could not refresh {path.name}, using cached copy: {exc})")
    return path


def _index_list(name: str, refresh: bool) -> pd.DataFrame:
    df = pd.read_csv(_get(f"{NSE}/indices/{name}.csv", LIST_DIR / f"{name}.csv", refresh))
    df.columns = [c.strip() for c in df.columns]
    df["Symbol"] = df["Symbol"].str.strip()
    return df.set_index("Symbol")


def _screen_caps(floor_cr: float) -> pd.Series:
    """All NSE equities above `floor_cr` from Yahoo's screener, a handful of
    requests in total. (Per-ticker lookups for ~2,400 symbols get rate-limited.)"""
    import yfinance as yf
    from yfinance import EquityQuery as Q

    query = Q("and", [Q("eq", ["region", "in"]), Q("eq", ["exchange", "NSI"]),
                      Q("gt", ["intradaymarketcap", floor_cr * CRORE])])
    caps: Dict[str, float] = {}
    offset, total = 0, None
    while total is None or offset < total:
        res = yf.screen(query, offset=offset, size=250, sortField="intradaymarketcap", sortAsc=False)
        quotes = res.get("quotes", [])
        total = int(res.get("total", 0))
        if not quotes:
            break
        for q in quotes:
            sym, cap = q.get("symbol", ""), q.get("marketCap")
            if sym.endswith(".NS") and cap:
                caps[sym[:-3]] = float(cap) / CRORE
        offset += len(quotes)
    if len(caps) < 300:  # a healthy result has well over a thousand names
        raise RuntimeError(f"screener returned only {len(caps)} stocks")
    return pd.Series(caps, name="mcap_cr")


def _market_caps(refresh: bool, floor_cr: float):
    """(caps in Rs crore, complete). `complete` is True when the caps come from a
    full screen, so a stock missing from them is known to be below the floor."""
    meta = {}
    if MCAP_META.exists():
        meta = json.loads(MCAP_META.read_text())
    cached = pd.Series(dtype=float, name="mcap_cr")
    if MCAP_PATH.exists():
        cached = pd.read_csv(MCAP_PATH, index_col=0)["mcap_cr"].dropna()
    complete = bool(meta.get("complete")) and meta.get("floor_cr", 1e18) <= floor_cr
    if complete and not refresh and not _stale(MCAP_PATH):
        return cached, True
    try:
        caps = _screen_caps(floor_cr)
        caps.round(1).to_csv(MCAP_PATH, index_label="symbol")
        MCAP_META.write_text(json.dumps({"complete": True, "floor_cr": floor_cr}))
        return caps, True
    except Exception as exc:
        print(f"  (market-cap screen unavailable: {str(exc)[:80]})")
        return cached, complete


KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments/NSE"  # public list, no login needed


def load_kite_tokens(refresh: bool = False) -> Dict[str, int]:
    """NSE symbol -> Zerodha instrument token, used to link each stock to its Kite chart.
    Refreshed daily; an empty mapping just means no links."""
    path = DATA_DIR / "cache" / "kite_instruments_public_nse.csv"
    if refresh or not path.exists() or time.time() - path.stat().st_mtime > 86400:
        try:
            req = urllib.request.Request(KITE_INSTRUMENTS_URL, headers={"X-Kite-Version": "3", "User-Agent": "nse-scanner"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
            if not body.startswith(b"instrument_token"):
                raise ValueError("unexpected response")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        except Exception as exc:
            if not path.exists():
                print(f"  (Kite chart links unavailable: {str(exc)[:80]})")
                return {}
    df = pd.read_csv(path, usecols=["instrument_token", "tradingsymbol", "instrument_type", "segment"])
    df = df[(df["instrument_type"] == "EQ") & (df["segment"] == "NSE")]
    return dict(zip(df["tradingsymbol"], df["instrument_token"].astype(int)))


def load_fo_symbols(refresh: bool = False) -> set:
    """Symbols with stock futures on NSE. Empty set if the list is unavailable."""
    try:
        text = _get(FO_URL, LIST_DIR / "fo_mktlots.csv", refresh).read_text()
    except Exception as exc:
        print(f"  (F&O list unavailable: {str(exc)[:80]})")
        return set()
    out, in_stocks = set(), False
    for line in text.splitlines():
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 2:
            continue
        if cols[0].lower().startswith("derivatives on individual"):
            in_stocks = True
        elif in_stocks and cols[1]:
            out.add(cols[1])
    return out


def load_universe(refresh: bool = False, min_cap_cr: float = 1000.0, scope: str = "all") -> pd.DataFrame:
    """Frame indexed by NSE symbol: name, industry, segment, mcap_cr, nifty200.

    scope="all"      every EQ-series stock with market cap >= min_cap_cr, plus all Nifty 200 members
    scope="nifty200" Nifty 200 members only
    """
    n200 = _index_list(NIFTY200, refresh)
    segs: Dict[str, pd.DataFrame] = {k: _index_list(v, refresh) for k, v in SEGMENTS.items()}

    eq = pd.read_csv(_get(EQUITY_URL, LIST_DIR / "EQUITY_L.csv", refresh))
    eq.columns = [c.strip() for c in eq.columns]
    eq = eq[eq["SERIES"].str.strip() == "EQ"]
    uni = pd.DataFrame({"name": eq["NAME OF COMPANY"].str.strip().values,
                        "listed": pd.to_datetime(eq["DATE OF LISTING"].str.strip(), format="%d-%b-%Y",
                                                 errors="coerce").values},
                       index=eq["SYMBOL"].str.strip().values)
    for sym in n200.index.difference(uni.index):  # safety: index member missing from the list
        uni.loc[sym, "name"] = n200.at[sym, "Company Name"]

    uni["industry"] = ""
    uni["segment"] = OTHER
    for seg in reversed(list(SEGMENTS)):          # reversed so the first segment wins
        members = segs[seg].index.intersection(uni.index)
        uni.loc[members, "segment"] = seg
        uni.loc[members, "industry"] = segs[seg].loc[members, "Industry"]
    uni["nifty200"] = uni.index.isin(n200.index)
    uni["fo"] = uni.index.isin(load_fo_symbols(refresh))

    caps, complete = _market_caps(refresh, min(SCREEN_FLOOR_CR, min_cap_cr))
    uni["mcap_cr"] = caps.reindex(uni.index)
    if scope == "nifty200":
        uni = uni[uni["nifty200"]]
    elif complete:
        uni = uni[(uni["mcap_cr"] >= min_cap_cr) | uni["nifty200"]]
    else:
        # Caps are missing for some stocks. Index members (Nifty 500 + Microcap
        # 250) with an unknown cap are kept; non-members need a known cap.
        in_index = uni["segment"] != OTHER
        uni = uni[(uni["mcap_cr"] >= min_cap_cr) | (uni["mcap_cr"].isna() & in_index)]
        print("  WARNING: market caps are incomplete, so the cap floor is only partly applied: "
              "index members with an unknown cap are included, other stocks with an unknown cap are not.")
    uni.attrs["caps_complete"] = complete or scope == "nifty200"
    uni.index.name = "symbol"
    return uni.sort_index()
