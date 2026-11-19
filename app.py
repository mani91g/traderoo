#!/usr/bin/env python3
"""Local web interface for the scanner: browse past scans and run a new one.

    .venv/bin/python app.py            # then open http://localhost:8765

It serves the reports that scan.py writes to reports/, adding a bar at the top
with a date picker for older scans and a "Run new scan" button. By default the server only
listens on this machine. `--lan` opens it to your local network so a phone on
the same Wi-Fi can use it and install it to the home screen.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import webbrowser
import zlib
from datetime import datetime
from html import escape as html_escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REPORT_LINE = re.compile(r"scan_(\d{4}-\d{2}-\d{2})\.html")


def make_icon(size: int) -> bytes:
    """App icon as a PNG, drawn here so the project needs no image files or
    imaging library: a dark tile with three rising green bars."""
    bg, fg = (17, 19, 22), (63, 202, 130)
    bars = ((0.22, 0.60), (0.43, 0.44), (0.64, 0.26))   # (left edge, top) as fractions
    width, bottom = 0.15, 0.76
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter type: none
        fy = y / size
        for x in range(size):
            fx = x / size
            on = any(left <= fx < left + width and top <= fy < bottom for left, top in bars)
            rows.extend(fg if on else bg)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


ICONS = {180: make_icon(180), 512: make_icon(512)}
MANIFEST = json.dumps({
    "name": "NSE Scanner", "short_name": "Scanner", "start_url": "/", "display": "standalone",
    "background_color": "#111316", "theme_color": "#111316",
    "icons": [{"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
              {"src": "/icon-180.png", "sizes": "180x180", "type": "image/png"}],
})
# Tags that let iOS/Android install the site to the home screen as a full-screen app.
HEAD_TAGS = (
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
    '<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-title" content="Scanner">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
    '<meta name="theme-color" content="#f6f7f9" media="(prefers-color-scheme: light)">'
    '<meta name="theme-color" content="#111316" media="(prefers-color-scheme: dark)">'
    '<link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/icon-180.png">'
)


class ScanJob:
    """At most one scan at a time, run as a subprocess of scan.py."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.started = 0.0
        self.last_line = ""
        self.result_date: Optional[str] = None
        self.error: Optional[str] = None

    def start(self) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running, self.started = True, time.time()
            self.last_line, self.result_date, self.error = "Starting…", None, None
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self) -> None:
        tail: List[str] = []
        try:
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "scan.py"), "--fresh-prices"],
                cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if not line or "OpenSSL" in line or "warnings.warn" in line:
                    continue
                tail = (tail + [line])[-15:]
                if line.startswith(("Universe:", "prices:", "Data as of", "Fetching")):
                    self.last_line = line
                m = REPORT_LINE.search(line)
                if m and line.startswith("Report:"):
                    self.result_date = m.group(1)
            code = proc.wait()
            if code != 0 or not self.result_date:
                self.error = "Scan failed: " + (tail[-1] if tail else f"exit code {code}")
        except Exception as exc:  # e.g. scan.py missing
            self.error = f"Scan failed: {exc}"
        finally:
            self.running = False

    def status(self) -> dict:
        return {
            "running": self.running,
            "elapsed": int(time.time() - self.started) if self.running else 0,
            "line": self.last_line,
            "date": self.result_date,
            "error": self.error,
        }


JOB = ScanJob()


def scan_dates() -> List[str]:
    """Dates that have a saved report, newest first."""
    found = [m.group(1) for p in REPORTS.glob("scan_*.html") if (m := REPORT_LINE.search(p.name))]
    return sorted(found, reverse=True)


BAR_CSS = """
#appbar{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);
padding:8px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:13px}
#appbar select,#appbar button,#appbar a{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;
background:var(--bg);color:var(--ink);text-decoration:none}
#appbar button{background:var(--accent);border-color:var(--accent);color:var(--bg);font-weight:600;cursor:pointer}
#appbar button:disabled{opacity:.55;cursor:default}#appstat{color:var(--mute)}#appstat.err{color:var(--down)}
#appbar .old{color:var(--down);font-weight:600}
#appbar details.menu{position:relative;margin-right:4px}
#appbar details.menu summary{list-style:none;cursor:pointer;user-select:none;padding:6px 12px;border:1px solid var(--line);
border-radius:8px;background:var(--bg);color:var(--ink);font-weight:600}
#appbar details.menu summary::-webkit-details-marker{display:none}
#appbar details.menu[open] summary{background:var(--ink);color:var(--card);border-color:var(--ink)}
#appbar details.menu div{position:absolute;top:calc(100% + 6px);left:0;min-width:220px;background:var(--card);
border:1px solid var(--line);border-radius:10px;padding:6px;box-shadow:0 8px 24px rgba(0,0,0,.18);z-index:10}
#appbar details.menu div a{display:block;border:0;background:none;padding:9px 10px;border-radius:7px}
#appbar details.menu div a:hover{background:var(--bg)}#appbar details.menu div a.on{font-weight:700;color:var(--accent)}
#appbar{padding-top:calc(8px + env(safe-area-inset-top));padding-left:calc(16px + env(safe-area-inset-left));
padding-right:calc(16px + env(safe-area-inset-right))}
@media(max-width:640px){main{padding:14px 12px 48px}h1{font-size:19px}
 #appbar{gap:8px}#appbar select,#appbar button,#appbar a,#appbar details.menu summary{padding:9px 12px}
 .tabs button{max-width:none}.bar label{margin-left:0}th,td{padding:6px 8px}
 td:first-child small{max-width:120px}svg.spark{width:120px;height:40px}
 .segs{flex-wrap:wrap}:is(#pu,#pd,#nu,#bu,#bd) :is(th,td):nth-child(3){display:none}
 input,select,button{font-size:16px!important}}
a.calc{font-size:11px;font-weight:400;color:var(--accent);text-decoration:none;margin-left:6px}
"""

BAR_JS = """
(()=>{const sel=document.getElementById('appdate'),btn=document.getElementById('apprun'),st=document.getElementById('appstat');
sel?.addEventListener('change',()=>location.href='/scan/'+sel.value);
document.querySelectorAll('.pane').forEach(p=>{const d=(p.id==='pane-short'||p.dataset.dir==='short')?'&d=short':'';
  p.querySelectorAll('tbody td:first-child b').forEach(b=>{const a=document.createElement('a');a.className='calc';
    a.href='/calc?s='+encodeURIComponent(b.parentElement.dataset.v)+d;a.textContent='SL / target';a.title='Open in the calculator';b.appendChild(a)})});
if(!btn)return;
let wasRunning=false;
async function poll(){
  let s;try{s=await (await fetch('/api/status')).json()}catch(e){st.textContent='Server not reachable';return}
  btn.disabled=s.running;
  if(s.running){wasRunning=true;st.className='';st.textContent='Scanning… '+s.line+' ('+s.elapsed+'s)';setTimeout(poll,1500)}
  else if(wasRunning){wasRunning=false;
    if(s.error){st.className='err';st.textContent=s.error}else if(s.date){location.href='/scan/'+s.date}}
}
btn.addEventListener('click',async()=>{btn.disabled=true;st.className='';st.textContent='Starting…';
  await fetch('/api/run',{method:'POST',headers:{'X-Scanner':'1'}});wasRunning=true;poll()});
poll();})();
"""


def nav_html(active: str) -> str:
    """A menu button that shows the pages only when clicked; closes on an outside click or Escape."""
    items = (("scan", "/", "Scanner"), ("calc", "/calc", "SL & target calculator"),
             ("portfolio", "/portfolio", "Portfolio & GTT"))
    links = "".join(f'<a href="{href}"{" class=on" if key == active else ""}>{label}</a>' for key, href, label in items)
    script = ("<script>(()=>{const m=document.getElementById('appmenu');"
              "document.addEventListener('click',e=>{if(!m.contains(e.target))m.open=false});"
              "document.addEventListener('keydown',e=>{if(e.key==='Escape')m.open=false});})();</script>")
    return f'<details class="menu" id="appmenu"><summary>☰ Menu</summary><div>{links}</div></details>{script}'


def bar_html(current: Optional[str], active: str = "scan") -> str:
    if active != "scan":
        return f'<style>{BAR_CSS}</style><div id="appbar">{nav_html(active)}</div>'
    dates = scan_dates()
    opts = "".join(
        f'<option value="{d}"{" selected" if d == current else ""}>'
        f'{datetime.strptime(d, "%Y-%m-%d"):%a %d %b %Y}{" (latest)" if i == 0 else ""}</option>'
        for i, d in enumerate(dates)
    )
    old = '<span class="old">Viewing an older scan</span>' if current and dates and current != dates[0] else ""
    csv_link = f'<a href="/csv/{current}">Download CSV</a>' if current else ""
    picker = f'<label>Scan date <select id="appdate">{opts}</select></label>' if dates else ""
    return (f'<style>{BAR_CSS}</style><div id="appbar">{nav_html("scan")}{picker}{old}'
            f'<button id="apprun">Run new scan</button><span id="appstat"></span>'
            f'<span style="margin-left:auto"></span>{csv_link}</div>')


def calc_page() -> str:
    from scanner import calc_page as cp, report
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'{HEAD_TAGS}<title>SL &amp; target calculator</title>'
            f'<style>{report.CSS}{cp.CSS}</style></head><body>{bar_html(None, "calc")}{cp.BODY}'
            f'<script>{cp.JS}</script><script>{cp.KITE_JS}</script></body></html>')


def portfolio_page() -> str:
    from scanner import portfolio_page as pp, report
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'{HEAD_TAGS}<title>Portfolio &amp; GTT</title>'
            f'<style>{report.CSS}{pp.CSS}</style></head><body>{bar_html(None, "portfolio")}{pp.BODY}'
            f'<script>{pp.JS}</script></body></html>')


def latest_stocks() -> dict:
    """Price, ATR and levels for every stock in the most recent scan, for the calculator."""
    dates = scan_dates()
    path = REPORTS / f"scan_{dates[0]}.csv" if dates else None
    if not path or not path.exists():
        return {"date": None, "stocks": {}}

    def f(row: dict, key: str) -> Optional[float]:
        try:
            v = float(row.get(key, ""))
            return v if v == v else None  # drop NaN
        except ValueError:
            return None

    out = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            close = f(row, "close")
            if close:
                out[row["symbol"]] = {"name": row.get("name", ""), "close": close, "atr_pct": f(row, "atr_pct"),
                                      "up_level": f(row, "up_level"), "down_level": f(row, "down_level")}
    return {"date": dates[0], "stocks": out}


def page_for(date: str) -> Optional[str]:
    path = REPORTS / f"scan_{date}.html"
    if not path.exists():
        return None
    page = path.read_text(encoding="utf-8")
    page = page.replace("<head>", "<head>" + HEAD_TAGS, 1)
    page = page.replace("<body>", "<body>" + bar_html(date), 1)
    return page.replace("</body>", f"<script>{BAR_JS}</script></body>", 1)


def empty_page() -> str:
    from scanner import report
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">{HEAD_TAGS}<title>Scanner</title>'
            f'<style>{report.CSS}</style></head><body>{bar_html(None)}<main><h1>No scans yet</h1>'
            f'<p class="sub">Press "Run new scan" to create the first one. It takes a minute or two.</p></main>'
            f'<script>{BAR_JS}</script></body></html>')


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _is_local(self) -> bool:
        """True only for requests made on this Mac. Everything that touches the
        Zerodha account is refused for other devices, even in --lan mode."""
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _kite_get(self, path: str, query: dict) -> None:
        from scanner import kite
        if path == "/api/kite/portfolio":
            if not self._is_local():
                self._json({"error": "Your portfolio is only available on the Mac running the scanner."}, 403)
                return
            try:
                self._json(kite.portfolio())
            except kite.KiteError as exc:
                self._json({"error": str(exc)}, 400)
            return
        if path == "/api/kite/status":
            if not self._is_local():
                self._json({"local": False, "configured": False, "connected": False, "user": ""})
            else:
                kite.ensure_config_file()
                self._json({"local": True, **kite.status()})
            return
        if not self._is_local():
            self._send(403, b"Zerodha actions are only available on the Mac running the scanner.", "text/plain")
            return
        try:
            if path == "/kite/login":
                back = (query.get("back") or ["/calc"])[0]
                self._send(302, b"", "text/plain", {"Location": kite.login_url(back)})
            else:  # /kite/callback
                token = (query.get("request_token") or [""])[0]
                if (query.get("status") or [""])[0] != "success" or not token:
                    raise kite.KiteError("Zerodha login was cancelled or failed.")
                kite.complete_login(token)
                back = (query.get("back") or ["/calc"])[0]
                self._send(302, b"", "text/plain", {"Location": back if back in ("/calc", "/portfolio") else "/calc"})
        except kite.KiteError as exc:
            msg = html_escape(str(exc))
            self._send(400, f'<p style="font:16px sans-serif;padding:24px">{msg} <a href="/calc">Back to the calculator</a></p>'
                       .encode(), "text/html; charset=utf-8")

    def _kite_post(self) -> None:
        """Preview or place a stop-loss + target GTT. Placing needs "confirm": true."""
        from scanner import kite
        if not self._is_local():
            self._json({"error": "Orders can only be placed from the Mac running the scanner."}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(min(length, 10000)) or b"{}")
            ltp = req.get("ltp")
            ticket = kite.build_ticket(str(req.get("symbol", "")), int(req.get("qty", 0)), float(req.get("stop", 0)),
                                       float(req.get("target", 0)), float(req.get("entry", 0)),
                                       float(req.get("buffer_pct", 0.5)),
                                       exchange=str(req.get("exchange", "NSE")), product=str(req.get("product", "CNC")),
                                       side=int(req.get("side", 1)), ltp=float(ltp) if ltp else None)
            if req.get("confirm") is True:
                ticket["trigger_id"] = kite.place_gtt(ticket)
            self._json(ticket)
        except kite.KiteError as exc:
            self._json({"error": str(exc)}, 400)
        except (ValueError, TypeError):
            self._json({"error": "The order details were incomplete."}, 400)

    def do_GET(self) -> None:  # noqa: N802
        path, _, qs = self.path.partition("?")
        if path in ("/api/kite/status", "/api/kite/portfolio", "/kite/login", "/kite/callback"):
            self._kite_get(path, parse_qs(qs))
        elif path == "/":
            dates = scan_dates()
            if dates:
                self._send(302, b"", "text/plain", {"Location": f"/scan/{dates[0]}"})
            else:
                self._send(200, empty_page().encode(), "text/html; charset=utf-8")
        elif path.startswith("/scan/") and DATE_RE.match(path[6:]):
            page = page_for(path[6:])
            if page is None:
                self._send(404, b"No scan saved for that date.", "text/plain")
            else:
                self._send(200, page.encode(), "text/html; charset=utf-8")
        elif path.startswith("/csv/") and DATE_RE.match(path[5:]):
            f = REPORTS / f"scan_{path[5:]}.csv"
            if f.exists():
                self._send(200, f.read_bytes(), "text/csv",
                           {"Content-Disposition": f'attachment; filename="{f.name}"'})
            else:
                self._send(404, b"No CSV for that date.", "text/plain")
        elif path == "/manifest.webmanifest":
            self._send(200, MANIFEST.encode(), "application/manifest+json")
        elif path in ("/icon-180.png", "/icon-512.png"):
            self._send(200, ICONS[int(path[6:9])], "image/png")
        elif path == "/portfolio":
            self._send(200, portfolio_page().encode(), "text/html; charset=utf-8")
        elif path == "/calc":
            self._send(200, calc_page().encode(), "text/html; charset=utf-8")
        elif path == "/api/stocks":
            self._json(latest_stocks())
        elif path == "/api/status":
            self._json(JOB.status())
        elif path == "/api/scans":
            self._json({"dates": scan_dates()})
        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        # The custom header cannot be sent by a plain cross-site form, so other
        # web pages open in the browser cannot trigger scans.
        if self.headers.get("X-Scanner") != "1" or self.path not in ("/api/run", "/api/kite/gtt"):
            self._send(404, b"Not found", "text/plain")
        elif self.path == "/api/kite/gtt":
            self._kite_post()
        else:
            self._json({"started": JOB.start()})

    def log_message(self, fmt: str, *args) -> None:  # keep the terminal quiet
        return


def _lan_ip() -> Optional[str]:
    """This machine's address on the local network (no data is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))  # reserved test address; only selects the outgoing interface
            ip = sock.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def _is_scanner(url: str) -> bool:
    """True if a copy of this app is already answering at `url`."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{url}/api/status", timeout=3) as resp:
            return "running" in json.loads(resp.read())
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true", help="do not open the browser")
    ap.add_argument("--lan", action="store_true",
                    help="also accept connections from other devices on your network (e.g. your phone). "
                         "Anyone on the same Wi-Fi can then view scans and start one.")
    args = ap.parse_args()
    REPORTS.mkdir(exist_ok=True)
    url = f"http://localhost:{args.port}"
    try:
        server = ThreadingHTTPServer(("0.0.0.0" if args.lan else "127.0.0.1", args.port), Handler)
    except OSError:
        if _is_scanner(url):
            print(f"The scanner is already running at {url}; opening it.")
            if not args.no_open:
                webbrowser.open(url)
            return 0
        print(f"Port {args.port} is in use by another program. Try: .venv/bin/python app.py --port {args.port + 1}",
              file=sys.stderr)
        return 1
    print(f"Scanner running at {url}  (Ctrl+C to stop)", flush=True)
    if args.lan:
        ip = _lan_ip()
        if ip:
            print(f"On your phone (same Wi-Fi): http://{ip}:{args.port}\n"
                  "  In Safari: Share > Add to Home Screen to install it as an app.", flush=True)
        else:
            print("Could not work out this Mac's network address; check System Settings > Wi-Fi > Details.", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
