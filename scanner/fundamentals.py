"""A simple, transparent fundamentals check for the stocks the screeners list.

Data comes from Yahoo Finance's company summary (latest reported figures) and
is cached for a week per stock. Six checks, each pass or fail:

    1. Profitable          net profit margin above 0
    2. Return on equity    ROE of 12% or more
    3. Revenue growing     latest quarter's revenue up on a year earlier
    4. Earnings growing    latest quarter's earnings up on a year earlier
    5. Debt manageable     debt / equity below 1.0   (skipped for financial companies)
    6. Cash generation     operating cash flow above 0 (skipped for financial companies)

Score = checks passed / checks with data x 100. A stock counts as
"fundamentally strong" when it is profitable, has data for at least four
checks and passes at least two thirds of them. These thresholds are defaults,
not tested against returns.
"""
from __future__ import annotations

import json
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Iterable, List, Optional

warnings.filterwarnings("ignore", message=".*OpenSSL.*")

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "fundamentals.json"
TTL_SEC = 7 * 86400
FIELDS = ("sector", "returnOnEquity", "profitMargins", "revenueGrowth", "earningsGrowth",
          "earningsQuarterlyGrowth", "debtToEquity", "operatingCashflow")
MIN_ROE = 0.12
MAX_DE = 1.0
STRONG_SHARE = 2 / 3
MIN_CHECKS = 4


def fetch(symbols: Iterable[str]) -> Dict[str, dict]:
    """Yahoo fundamentals per symbol, from the cache where fresh. Stops early if Yahoo rate-limits."""
    cache: Dict[str, dict] = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    now = time.time()
    todo = [s for s in dict.fromkeys(symbols) if now - cache.get(s, {}).get("t", 0) > TTL_SEC]
    if todo:
        import yfinance as yf
        print(f"  Fetching fundamentals for {len(todo)} stocks (cached for a week)...", flush=True)
        blocked = False

        def one(sym: str) -> Optional[dict]:
            nonlocal blocked
            if blocked:
                return None
            for attempt in range(2):
                try:
                    info = yf.Ticker(f"{sym}.NS").info or {}
                    return {k: info.get(k) for k in FIELDS}
                except Exception as exc:
                    if "Rate" in type(exc).__name__ or "Too Many" in str(exc):
                        if attempt == 0:
                            time.sleep(5)
                            continue
                        blocked = True
                    return None
            return None

        with ThreadPoolExecutor(4) as pool:
            for sym, data in zip(todo, pool.map(one, todo)):
                if data is not None:
                    cache[sym] = {"t": now, "d": data}
        if blocked:
            print("  (Yahoo rate-limited the fundamentals download; the rest will be fetched on the next scan)")
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    return {s: cache[s]["d"] for s in symbols if s in cache}


def _pct(v: float) -> str:
    return f"{v * 100:+.0f}%" if v is not None else "–"


def score(d: Optional[dict]) -> dict:
    """{'score': 0-100 or None, 'strong': bool, 'checks': [(name, passed or None, detail)], 'passed', 'counted'}."""
    if not d:
        return {"score": None, "strong": False, "checks": [], "passed": 0, "counted": 0,
                "summary": "No fundamental data from Yahoo"}
    financial = (d.get("sector") or "") == "Financial Services"
    g = d.get("earningsGrowth")
    if g is None:
        g = d.get("earningsQuarterlyGrowth")
    pm, roe, rg, de, ocf = (d.get("profitMargins"), d.get("returnOnEquity"), d.get("revenueGrowth"),
                            d.get("debtToEquity"), d.get("operatingCashflow"))

    def chk(name, value, test, detail):
        return (name, None if value is None else bool(test(value)), detail)

    checks: List[tuple] = [
        chk("Profitable", pm, lambda v: v > 0, f"net margin {_pct(pm)}" if pm is not None else "no data"),
        chk("Return on equity ≥ 12%", roe, lambda v: v >= MIN_ROE, f"ROE {roe * 100:.0f}%" if roe is not None else "no data"),
        chk("Revenue growing", rg, lambda v: v > 0, f"revenue {_pct(rg)} vs a year ago" if rg is not None else "no data"),
        chk("Earnings growing", g, lambda v: v > 0, f"earnings {_pct(g)} vs a year ago" if g is not None else "no data"),
    ]
    if financial:
        checks += [("Debt / equity below 1", None, "not used for financial companies"),
                   ("Positive operating cash flow", None, "not used for financial companies")]
    else:
        # Yahoo reports debt / equity as a percentage (84 means 0.84).
        checks += [chk("Debt / equity below 1", de, lambda v: v / 100 < MAX_DE,
                       f"debt / equity {de / 100:.2f}" if de is not None else "no data"),
                   chk("Positive operating cash flow", ocf, lambda v: v > 0,
                       f"operating cash flow ₹{ocf / 1e7:,.0f} cr" if ocf is not None else "no data")]
    counted = [c for c in checks if c[1] is not None]
    passed = sum(1 for c in counted if c[1])
    sc = round(passed / len(counted) * 100) if counted else None
    strong = bool(counted) and len(counted) >= MIN_CHECKS and checks[0][1] is True and passed / len(counted) >= STRONG_SHARE
    if not counted:
        summary = "No fundamental data from Yahoo"
    elif len(counted) < MIN_CHECKS:
        summary = f"Only {len(counted)} of 6 checks have data"
    elif checks[0][1] is not True:
        summary = "Not profitable"
    else:
        summary = f"Passes {passed} of {len(counted)} checks"
    return {"score": sc, "strong": strong, "checks": checks, "passed": passed, "counted": len(counted),
            "summary": summary}
