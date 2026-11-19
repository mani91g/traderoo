"""Zerodha Kite Connect client: log in, then place a stop-loss + target GTT.

Only what the calculator needs is implemented, using Kite Connect v3
(https://kite.trade/docs/connect/v3/):

* login flow     -> request_token -> access_token (valid until about 6 AM next day)
* two-leg GTT    -> an OCO pair of SELL LIMIT orders on a delivery (CNC) holding:
                    one below the market (stop-loss), one above (target).
                    When either triggers, Zerodha cancels the other.

Credentials live in data/kite.json, which you fill in yourself:
    {"api_key": "...", "api_secret": "..."}
The day's access token is kept in data/kite_session.json. Both files are
readable only by your user and neither value is ever printed or sent anywhere
except to Zerodha.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("KITE_CONFIG_DIR", ROOT / "data"))
CONFIG_PATH = CONFIG_DIR / "kite.json"
SESSION_PATH = CONFIG_DIR / "kite_session.json"
INSTRUMENTS_PATH = CONFIG_DIR / "cache" / "kite_instruments_nse.csv"
# Overridable so the flow can be tested against a local stand-in server.
API_BASE = os.environ.get("KITE_API_BASE", "https://api.kite.trade")
LOGIN_BASE = os.environ.get("KITE_LOGIN_BASE", "https://kite.zerodha.com")
IST = ZoneInfo("Asia/Kolkata")


class KiteError(Exception):
    """A problem the user can act on; the message is shown in the app."""


# ------------------------------------------------------------ credentials --

def ensure_config_file() -> None:
    """Create an empty, private kite.json for the user to fill in."""
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps({"api_key": "", "api_secret": ""}, indent=2) + "\n")
        os.chmod(CONFIG_PATH, 0o600)


def _config() -> Optional[Tuple[str, str]]:
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return None
    key, secret = str(cfg.get("api_key", "")).strip(), str(cfg.get("api_secret", "")).strip()
    return (key, secret) if key and secret else None


def is_configured() -> bool:
    return _config() is not None


def _session() -> Optional[dict]:
    try:
        return json.loads(SESSION_PATH.read_text())
    except (OSError, ValueError):
        return None


def _save_session(data: dict) -> None:
    SESSION_PATH.write_text(json.dumps(data))
    os.chmod(SESSION_PATH, 0o600)


# ------------------------------------------------------------------ HTTP ---

def _request(method: str, path: str, data: Optional[dict] = None, auth: bool = True, raw: bool = False):
    cfg = _config()
    if not cfg:
        raise KiteError("Zerodha API key is not set up. Add your api_key and api_secret to data/kite.json.")
    headers = {"X-Kite-Version": "3", "User-Agent": "nse-scanner"}
    if auth:
        sess = _session()
        if not sess:
            raise KiteError("Not connected to Zerodha. Use Connect to Zerodha first.")
        headers["Authorization"] = f"token {cfg[0]}:{sess['access_token']}"
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(API_BASE + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read())
        except ValueError:
            err = {}
        if err.get("error_type") == "TokenException":
            SESSION_PATH.unlink(missing_ok=True)
            raise KiteError("Your Zerodha session has expired. Connect to Zerodha again.") from None
        raise KiteError(f"Zerodha rejected the request: {err.get('message') or f'HTTP {exc.code}'}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise KiteError(f"Could not reach Zerodha: {getattr(exc, 'reason', exc)}") from None
    if raw:
        return payload
    out = json.loads(payload)
    if out.get("status") != "success":
        raise KiteError(f"Zerodha rejected the request: {out.get('message', 'unknown error')}")
    return out["data"]


# ----------------------------------------------------------------- login ---

def login_url(back: str = "/calc") -> str:
    """Zerodha's login page. `back` is the app page to return to afterwards."""
    cfg = _config()
    if not cfg:
        raise KiteError("Zerodha API key is not set up. Add your api_key and api_secret to data/kite.json.")
    url = f"{LOGIN_BASE}/connect/login?v=3&api_key={urllib.parse.quote(cfg[0])}"
    if back != "/calc":
        url += "&redirect_params=" + urllib.parse.quote(urllib.parse.urlencode({"back": back}))
    return url


def complete_login(request_token: str) -> str:
    """Exchange the one-time request_token for the day's access token. Returns the user's name."""
    key, secret = _config() or ("", "")
    checksum = hashlib.sha256((key + request_token + secret).encode()).hexdigest()
    data = _request("POST", "/session/token",
                    {"api_key": key, "request_token": request_token, "checksum": checksum}, auth=False)
    _save_session({"access_token": data["access_token"], "user_id": data.get("user_id", ""),
                   "user_name": data.get("user_shortname") or data.get("user_name", ""), "at": time.time()})
    return data.get("user_name", "")


def status() -> dict:
    """{configured, connected, user}. `connected` is confirmed with Zerodha, not assumed."""
    if not is_configured():
        return {"configured": False, "connected": False, "user": ""}
    sess = _session()
    if not sess:
        return {"configured": True, "connected": False, "user": ""}
    try:
        _request("GET", "/user/profile")
    except KiteError:
        return {"configured": True, "connected": False, "user": ""}
    return {"configured": True, "connected": True, "user": sess.get("user_name") or sess.get("user_id", "")}


# ------------------------------------------------------------ market data --

def _instruments(exchange: str = "NSE") -> Dict[str, float]:
    """Trading symbol -> tick size for one exchange, from Zerodha's daily instrument list (cached per day)."""
    path = INSTRUMENTS_PATH.with_name(f"kite_instruments_{exchange.lower()}.csv")
    today = datetime.now(IST).strftime("%Y-%m-%d")
    fresh = path.exists() and datetime.fromtimestamp(path.stat().st_mtime, IST).strftime("%Y-%m-%d") == today
    if not fresh:
        payload = _request("GET", f"/instruments/{exchange}", raw=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    out = {}
    for row in csv.DictReader(io.StringIO(path.read_text())):
        if exchange in ("NSE", "BSE") and row.get("instrument_type") != "EQ":
            continue
        try:
            out[row["tradingsymbol"]] = float(row["tick_size"])
        except (KeyError, ValueError):
            continue
    return out


def _round_tick(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 2)


def last_price(symbol: str, exchange: str = "NSE") -> Optional[float]:
    """Live last price, or None if this API plan has no market quotes."""
    key = f"{exchange}:{symbol}"
    try:
        data = _request("GET", "/quote/ltp?" + urllib.parse.urlencode({"i": key}))
        return float(data[key]["last_price"])
    except (KiteError, KeyError, ValueError, TypeError):
        return None


def holding_qty(symbol: str) -> Optional[int]:
    """Shares of `symbol` in the demat account including T1, or None if it could not be read."""
    try:
        for h in _request("GET", "/portfolio/holdings"):
            if h.get("tradingsymbol") == symbol and h.get("exchange", "NSE") in ("NSE", "BSE"):
                return int(h.get("quantity", 0)) + int(h.get("t1_quantity", 0))
        return 0
    except KiteError:
        return None


# ------------------------------------------------------------- portfolio ---

def portfolio() -> dict:
    """Everything open in the account, ready for the Portfolio page.

    Holdings and today's delivery (CNC) trades are merged per stock, since a GTT
    has to cover the whole quantity. Carry-forward (NRML) positions, long or
    short, are listed as they are. Intraday (MIS) positions are listed but
    marked, because Zerodha's GTT does not support them.
    """
    rows: Dict[tuple, dict] = {}
    tokens: Dict[tuple, int] = {}

    def add(exchange, symbol, product, qty, avg, ltp, source):
        key = (exchange, symbol, product)
        r = rows.get(key)
        if r is None:
            rows[key] = {"exchange": exchange, "symbol": symbol, "product": product, "qty": qty,
                         "avg": avg, "ltp": ltp, "sources": [source]}
            return
        total = r["qty"] + qty
        if total and (r["qty"] > 0) == (qty > 0):          # adding in the same direction: blend the cost
            r["avg"] = (r["avg"] * r["qty"] + avg * qty) / total
        r["qty"], r["ltp"] = total, ltp or r["ltp"]
        r["sources"].append(source)

    for h in _request("GET", "/portfolio/holdings"):
        if h.get("instrument_token"):
            tokens[(h.get("exchange", "NSE"), h["tradingsymbol"])] = int(h["instrument_token"])
        qty = int(h.get("quantity", 0)) + int(h.get("t1_quantity", 0))
        if qty > 0:
            add(h.get("exchange", "NSE"), h["tradingsymbol"], "CNC", qty,
                float(h.get("average_price") or 0), float(h.get("last_price") or 0), "holding")
    for pos in _request("GET", "/portfolio/positions").get("net", []):
        if pos.get("instrument_token"):
            tokens[(pos.get("exchange", "NSE"), pos["tradingsymbol"])] = int(pos["instrument_token"])
        qty = int(pos.get("quantity", 0))
        if qty == 0:
            continue
        add(pos.get("exchange", "NSE"), pos["tradingsymbol"], pos.get("product", ""), qty,
            float(pos.get("average_price") or 0), float(pos.get("last_price") or 0), "position")

    active: Dict[tuple, list] = {}
    for g in _request("GET", "/gtt/triggers"):
        if g.get("status") != "active":
            continue
        cond = g.get("condition") or {}
        legs = g.get("orders") or []
        product = legs[0].get("product", "") if legs else ""
        active.setdefault((cond.get("exchange"), cond.get("tradingsymbol"), product), []).append({
            "id": g.get("id"), "type": g.get("type"), "triggers": cond.get("trigger_values", []),
            "qty": legs[0].get("quantity") if legs else None,
        })

    out = []
    for key, r in rows.items():
        if r["qty"] == 0:
            continue
        r["avg"] = round(r["avg"], 2)
        r["gtts"] = active.get(key, [])
        r["token"] = tokens.get((r["exchange"], r["symbol"]))
        r["gtt_ok"] = r["product"] in ("CNC", "NRML")
        r["value"] = round(abs(r["qty"]) * (r["ltp"] or r["avg"]), 2)
        out.append(r)
    out.sort(key=lambda r: -r["value"])

    funds = None
    try:
        eq = _request("GET", "/user/margins/equity")
        funds = float(eq.get("net"))
    except (KiteError, TypeError, ValueError):
        pass
    return {"rows": out, "cash": funds}


# ------------------------------------------------------------------- GTT ---

def build_ticket(symbol: str, qty: int, stop: float, target: float, ref_price: float,
                 buffer_pct: float = 0.5, exchange: str = "NSE", product: str = "CNC",
                 side: int = 1, ltp: Optional[float] = None) -> dict:
    """Work out exactly what would be sent, without sending it.

    side=1 protects a long position (two SELL legs: stop below, target above);
    side=-1 protects a short position (two BUY legs: stop above, target below).
    The stop leg's limit price sits `buffer_pct` beyond its trigger so the
    order can still fill while the price is moving against you; the target
    leg's limit equals its trigger. Prices are rounded to the tick size.
    """
    symbol, exchange, product = symbol.strip().upper(), exchange.strip().upper(), product.strip().upper()
    if not symbol:
        raise KiteError("Enter the NSE symbol of the stock.")
    if not (isinstance(qty, int) and qty > 0):
        raise KiteError("Quantity must be a whole number of shares.")
    if side not in (1, -1):
        raise KiteError("Unknown direction.")
    if product not in ("CNC", "NRML"):
        raise KiteError(f"Zerodha's GTT does not support {product} (intraday) positions. Use a stop-loss order in Kite.")
    if not (0 <= buffer_pct <= 5):
        raise KiteError("The limit buffer must be between 0% and 5%.")
    ticks = _instruments(exchange)
    if symbol not in ticks:
        raise KiteError(f"{symbol} is not in Zerodha's {exchange} instrument list.")
    tick = ticks[symbol]
    live = last_price(symbol, exchange)
    price_now = live if live is not None else (ltp if ltp else ref_price)
    sl_trigger, tgt_trigger = _round_tick(stop, tick), _round_tick(target, tick)
    if side == 1 and not (0 < sl_trigger < price_now < tgt_trigger):
        raise KiteError(f"The stop ({sl_trigger}) must be below, and the target ({tgt_trigger}) above, "
                        f"the current price ({price_now}).")
    if side == -1 and not (0 < tgt_trigger < price_now < sl_trigger):
        raise KiteError(f"For a short, the stop ({sl_trigger}) must be above, and the target ({tgt_trigger}) below, "
                        f"the current price ({price_now}).")
    sl_limit = _round_tick(sl_trigger * (1 - side * buffer_pct / 100), tick)
    lower, upper = sorted([(sl_trigger, sl_limit, "stop"), (tgt_trigger, tgt_trigger, "target")])
    return {
        "symbol": symbol, "exchange": exchange, "product": product, "side": side, "qty": qty, "tick": tick,
        "ltp": price_now, "ltp_live": live is not None,
        "sl_trigger": sl_trigger, "sl_limit": sl_limit, "tgt_trigger": tgt_trigger, "tgt_limit": tgt_trigger,
        # Zerodha matches orders to trigger_values by position, lower trigger first.
        "legs": [lower, upper],
        "holding": holding_qty(symbol) if product == "CNC" and side == 1 else None,
    }


def place_gtt(ticket: dict) -> int:
    """Send the two-leg GTT described by `ticket`. Returns Zerodha's trigger id."""
    sym, qty, exch = ticket["symbol"], ticket["qty"], ticket.get("exchange", "NSE")
    action = "SELL" if ticket.get("side", 1) == 1 else "BUY"
    (low_trig, low_px, _), (high_trig, high_px, _) = ticket.get("legs") or [
        (ticket["sl_trigger"], ticket["sl_limit"], "stop"), (ticket["tgt_trigger"], ticket["tgt_limit"], "target")]
    leg = lambda price: {"exchange": exch, "tradingsymbol": sym, "transaction_type": action,  # noqa: E731
                         "quantity": qty, "order_type": "LIMIT", "product": ticket.get("product", "CNC"),
                         "price": price}
    data = _request("POST", "/gtt/triggers", {
        "type": "two-leg",
        "condition": json.dumps({"exchange": exch, "tradingsymbol": sym,
                                 "trigger_values": [low_trig, high_trig], "last_price": ticket["ltp"]}),
        "orders": json.dumps([leg(low_px), leg(high_px)]),
    })
    return int(data["trigger_id"])
