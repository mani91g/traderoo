"""Console tables and a self-contained HTML report."""
from __future__ import annotations

import html
import urllib.parse
from typing import Dict, List, Optional, Tuple

import pandas as pd

# (column key, header, format, tooltip). Headers listed in a section's "extra"
# set are hidden until the reader ticks "More columns".
Col = Tuple[str, str, str, str]

CLOSE: Col = ("close", "Close", "{:,.1f}", "Last close (adjusted)")
DAY: Col = ("chg_pct", "Day %", "{:+.1f}", "Change vs previous close")
CAP: Col = ("segment", "Cap", "{}", "Large = Nifty 100, Mid = Midcap 150, Small = Smallcap 250, Micro = Microcap 250, Other = none of these")
MCAP: Col = ("mcap_cr", "MCap ₹cr", "{:,.0f}", "Market capitalisation, Rs crore (Yahoo Finance)")
VOL: Col = ("vol_ratio", "Vol x", "{:.1f}", "Today's volume / prior 20-day average")
RS: Col = ("rs", "RS", "{:.0f}", "Relative strength rating within the scanned universe (1-99)")
RSI: Col = ("rsi", "RSI", "{:.0f}", "14-day RSI")
ATR: Col = ("atr_pct", "ATR %", "{:.1f}", "14-day ATR as % of price")
SQZ: Col = ("squeeze_pct", "Squeeze", "{:.0f}", "Bollinger-width percentile over 6 months (low = tight coil)")
TRADED: Col = ("turnover_cr", "Traded ₹cr", "{:,.0f}", "Median daily traded value over 20 days, Rs crore")


def pick_cols(side: str) -> List[Col]:
    return [
        (f"{side}_score", "Score", "{:.0f}", "Composite 0-100"),
        ("why", "Why it qualifies", "{}", "The main reasons this stock passed every gate"),
        CLOSE, DAY, CAP,
        (f"{side}_level", "Level", "{:,.1f}", "Prior 20-day high/low that was broken"),
        (f"{side}_dist_pct", "Dist %", "{:+.1f}", "Close relative to the level"),
        (f"{side}_tf", "Timeframe", "{}", "Daily, or Both if the weekly chart broke too"),
        VOL, RS, MCAP, TRADED, ATR,
    ]


def break_cols(side: str) -> List[Col]:
    return [
        ("break_score", "Score", "{:.0f}", "Composite 0-100 for the daily break (blank for weekly-only)"),
        (f"{side}_tf", "Timeframe", "{}", "Which chart the break shows on: Daily, Weekly or Both"),
        CLOSE, DAY, CAP,
        (f"{side}_level", "Daily level", "{:,.1f}", "Prior 20-day high/low"),
        VOL, RS,
        ("wk_chg_pct", "Week %", "{:+.1f}", "Change vs last week's close (week to date)"),
        (f"{side}_dist_pct", "vs daily %", "{:+.1f}", "Close relative to the daily level"),
        (f"{side}_wk_level", "Weekly level", "{:,.1f}", "Prior 20-week high/low"),
        (f"{side}_wk_dist_pct", "vs weekly %", "{:+.1f}", "Close relative to the weekly level"),
        ("wk_vol_ratio", "Wk vol x", "{:.1f}", "Week-to-date volume / 10-week average, prorated for sessions so far"),
        (f"{side}_tag", "Type", "{}", "Whether the daily level is also the 55-day or 52-week extreme"),
        MCAP, TRADED, RSI, ATR,
    ]


def setup_cols(side: str) -> List[Col]:
    return [
        (f"{side}_score", "Score", "{:.0f}", "Composite 0-100"),
        CLOSE, DAY, CAP,
        (f"{side}_level", "Level", "{:,.1f}", "Prior 20-day high/low being tested"),
        (f"{side}_dist_pct", "Dist %", "{:+.1f}", "Close relative to the level"),
        RS,
        (f"{side}_tag", "Type", "{}", "Whether the level is also the 55-day or 52-week extreme"),
        (f"{side}_age", "Base", "{:.0f}", "Bars since the level was set"),
        VOL, SQZ, MCAP, TRADED, RSI, ATR,
    ]


def momentum_cols(side: str) -> List[Col]:
    ext = ("off_52w_high", "Off high %", "{:+.1f}", "Distance from 52-week high") if side == "up" \
        else ("off_52w_low", "Off low %", "{:+.1f}", "Distance from 52-week low")
    return [
        (f"mom_{side}", "Score", "{:.0f}", "Composite 0-100"),
        CLOSE, DAY, CAP, RS,
        ("r3m", "3M %", "{:+.1f}", "63-day return"),
        ext,
        ("r1m", "1M %", "{:+.1f}", "21-day return"),
        ("r6m", "6M %", "{:+.1f}", "126-day return"),
        ("adx", "ADX", "{:.0f}", "14-day ADX (trend strength)"),
        MCAP, TRADED, RSI, ATR,
    ]


def screen_cols(ipo: bool) -> List[Col]:
    cols: List[Col] = [
        ("broke", "Closing above", "{}", "First close above the old all-time high, or how many closes in a row it has been above"),
        CLOSE, DAY,
        ("ath_level", "Old ATH", "{:,.1f}", "All-time high before today: the highest price on any earlier day, intraday highs included"),
        ("above_ath_pct", "Above it %", "{:+.1f}", "Close relative to the old all-time high"),
    ]
    if ipo:
        cols.append(("listed_str", "Listed", "{}", "NSE listing date"))
    cols += [CAP, MCAP, VOL, TRADED]
    return cols


def pullback_cols() -> List[Col]:
    return [
        ("broke", "Broke out", "{}", "Day it closed above its previous all-time high"),
        CLOSE, DAY,
        ("ath_level", "Breakout level", "{:,.1f}", "The old all-time high it closed above"),
        ("above_ath_pct", "Above it %", "{:+.1f}", "Close relative to the breakout level; near zero = testing it"),
        ("peak", "High since", "{:,.1f}", "Highest price since the breakout"),
        ("off_peak_pct", "Off high %", "{:+.1f}", "Close relative to the high since the breakout"),
        ("ipo_listed", "IPO", "{}", "Listing date, for IPOs from the last 12 months"),
        CAP, MCAP, VOL, TRADED,
    ]


def screen_sections(scr: pd.DataFrame, ipo_months: int, pb: Optional[pd.DataFrame] = None) -> List[dict]:
    """The Screeners tab: all-time-high breaks, then the same limited to recent IPOs."""
    common = ("Market cap ₹1,000 crore or more and today's close above the previous all-time high (the highest price "
              "on any earlier day). Trading above it during the day is not enough. The dashed line is the old high. "
              "● = volume ≥ 2× average.")
    ipo = scr[scr["ipo"]] if len(scr) else scr
    out = [
        {"key": "ath", "title": "Screener 1: all-time high breakouts", "note": common, "cols": screen_cols(False),
         "df": scr, "empty": "No stock with a market cap of ₹1,000 crore or more closed above its all-time high today."},
        {"key": "ipo", "title": "Screener 2: recent IPOs at all-time highs",
         "note": f"As screener 1, limited to companies that listed through an IPO in the last {ipo_months} months. "
                 "Stocks that already traded on BSE or NSE before their listing date are not counted as IPOs.",
         "cols": screen_cols(True), "df": ipo, "ipo_filter": True,
         "empty": f"No IPO from the last {ipo_months} months closed above its all-time high today."},
    ]
    if pb is not None:
        pb = pb.copy()
        if len(pb):
            pb["ipo_listed"] = pb["listed_str"].where(pb["ipo"], "")
        out.append({"key": "pb", "title": "Screener 3: pullbacks after an all-time-high breakout",
                    "note": "Market cap ₹1,000 crore or more. Closed above its previous all-time high in the last 10 sessions, "
                            "has since pulled back below its newest high, and still closes above the level it broke. "
                            "Closest to the breakout level first. The dashed line is that level.",
                    "cols": pullback_cols(), "df": pb,
                    "empty": "No recent all-time-high breakout is pulling back while holding above its breakout level."})
    for sec in out:
        sec.update({"tone": "up", "tab": "screens", "kind": "screen", "charts": True, "side": "ath",
                    "extra": ({CAP[1], MCAP[1], TRADED[1], "High since"} if sec["key"] == "pb" else
                              {CAP[1], MCAP[1], TRADED[1]} if not sec.get("ipo_filter") else {MCAP[1], TRADED[1]})})
    return out


# How many leading columns of each kind stay visible by default.
VISIBLE = {"pick": 6, "near": 6, "break": 8, "setup": 7, "momentum": 7}


def build_sections(m: pd.DataFrame, top: int, longs: pd.DataFrame, shorts: pd.DataFrame,
                   long_note: str, short_note: str, near: Optional[pd.DataFrame] = None) -> List[dict]:
    """Sections for the Long tab then the Short tab. The first of each tab is the picks."""
    out: List[dict] = []
    for side, tab, picks, note in (("up", "long", longs, long_note), ("down", "short", shorts, short_note)):
        up = side == "up"
        word = "above" if up else "below"

        def sec(kind, key, title, note, cols, df, charts=False, **kw):
            extra = {h for _, h, _, _ in cols[VISIBLE[kind]:]}
            return {"key": f"{key}{side[0]}", "title": title, "note": note, "cols": cols, "df": df, "tone": side,
                    "tab": tab, "kind": kind, "extra": extra, "charts": charts, "side": side, **kw}

        out.append(sec("pick", "p", f"Top picks: {tab}", note, pick_cols(side), picks, charts=True,
                       empty=f"No stock passes every {tab} gate today."))

        if up and near is not None and len(near):
            out.append(sec("near", "n", "Near misses",
                           "Clean breakouts with a qualifying score that failed exactly one long gate. Not picks.",
                           [("why", "Why it missed", "{}", "The one gate this stock failed") if c[0] == "why" else c
                            for c in pick_cols(side)], near, charts=True))

        brk = m[m[f"{side}_tf"] != ""].copy()
        brk["break_score"] = brk[f"{side}_score"].where(brk[f"{side}_status"] == "triggered")
        brk = brk.sort_values([f"{side}_tf_rank", "break_score"], ascending=[True, False])
        out.append(sec("break", "b", "All breakouts" if up else "All breakdowns",
                       f"Daily = closed {word} the prior 20-day level today. Weekly = this week's close so far is "
                       f"{word} the prior 20-week level (not backtested). ● = volume ≥ 2× average.",
                       break_cols(side), brk, charts=True))

        setups = m[m[f"{side}_status"] == "setup"].sort_values(f"{side}_score", ascending=False).head(top)
        out.append(sec("setup", "s", "Setups near a breakout" if up else "Setups near a breakdown",
                       f"{'Above' if up else 'Below'} the 50-DMA and within 1.5 ATR of the level, not yet through it.",
                       setup_cols(side), setups))

        flag, score = ("leader", "mom_up") if up else ("laggard", "mom_down")
        mom = m[m[flag]].sort_values(score, ascending=False).head(top)
        out.append(sec("momentum", "m", "Momentum leaders" if up else "Momentum laggards",
                       "RS ≥ 70 and above both the 50- and 200-DMA." if up else
                       "RS ≤ 30 and below both the 50- and 200-DMA.", momentum_cols(side), mom))
    return out


def _fmt(v, f: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "–"
    return f.format(v)


def print_console(sections: List[dict], verbose: bool = False) -> None:
    """Picks in full; other sections as one-line counts unless `verbose`."""
    for s in sections:
        df = s["df"]
        if s["kind"] not in ("pick", "near", "screen") and not verbose:
            print(f"  {s['title']}: {len(df)}")
            continue
        print(f"\n== {s['title']} ({len(df)}) ==")
        if df.empty:
            print("  " + s.get("empty", "none"))
            continue
        out = pd.DataFrame(index=df.index)
        for key, head, f, _ in s["cols"]:
            if verbose or head not in s["extra"]:
                out[head] = [_fmt(v, f) for v in df[key]]
        out.index.name = None
        print(out.to_string())
        if s["kind"] in ("pick", "screen"):
            print()


# ---------------------------------------------------------------- HTML ----

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#16191d;--mute:#667080;--line:#e3e6eb;--up:#0b8a4a;--down:#c9352b;
--upbg:#e5f5ec;--downbg:#fbeae8;--accent:#2f5bd8}
@media(prefers-color-scheme:dark){:root{--bg:#111316;--card:#1a1d22;--ink:#e8eaed;--mute:#98a1ae;--line:#2b3038;
--up:#3fca82;--down:#ff7b70;--upbg:#12301f;--downbg:#3a1a17;--accent:#8fb0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1280px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 2px}h2{font-size:16px;margin:0}
.sub{color:var(--mute);margin:0 0 16px}.warn{background:var(--downbg);color:var(--down);padding:8px 12px;border-radius:8px;margin:0 0 16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.tile span{color:var(--mute);font-size:12px}
nav{position:sticky;top:0;background:var(--bg);padding:8px 0;display:flex;gap:6px;flex-wrap:wrap;z-index:2}
nav a{padding:5px 10px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--ink);text-decoration:none;font-size:13px}
nav a i{font-style:normal;color:var(--mute);margin-left:4px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-top:16px;scroll-margin-top:52px}
section header{padding:12px 14px 8px;border-left:4px solid var(--mute);border-radius:12px 0 0 0}
section.up header{border-color:var(--up)}section.down header{border-color:var(--down)}
section header p{margin:2px 0 0;color:var(--mute);font-size:12.5px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 10px;text-align:right;white-space:nowrap;border-top:1px solid var(--line)}
th{font-size:12px;color:var(--mute);font-weight:600;cursor:pointer;user-select:none}th:hover{color:var(--ink)}
td[data-v="0"]{text-align:left}th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card)}
td:first-child b{display:block}td:first-child small{color:var(--mute);display:block;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.pos{color:var(--up)}.neg{color:var(--down)}.dot{color:var(--accent)}
.score{display:inline-block;min-width:34px;padding:1px 6px;border-radius:6px;font-weight:600;text-align:center}
.up .score{background:var(--upbg);color:var(--up)}.down .score{background:var(--downbg);color:var(--down)}
.empty{padding:14px;color:var(--mute)}svg.spark{vertical-align:middle}
footer{color:var(--mute);font-size:12px;margin-top:24px}
.stats{color:var(--mute);margin:0 0 14px;font-size:13px}.stats b{color:var(--ink);font-weight:600}
.tabs{display:flex;gap:8px;margin-bottom:10px}.tabs button{flex:1;max-width:220px;padding:10px 14px;border:1px solid var(--line);
border-radius:10px;background:var(--card);color:var(--ink);font:inherit;font-size:15px;font-weight:600;cursor:pointer;text-align:left}
.tabs button i{font-style:normal;font-weight:400;color:var(--mute);font-size:12.5px;display:block}
.tabs button.on[data-tab=long]{border-color:var(--up);box-shadow:inset 0 -3px 0 var(--up)}
.tabs button.on[data-tab=short]{border-color:var(--down);box-shadow:inset 0 -3px 0 var(--down)}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:13px;color:var(--mute)}.bar label{cursor:pointer;margin-left:auto}
.pane{display:none}.pane.on{display:block}
.fs,.fw{display:none}body.showscore .fs{display:table-cell}body.strong .fw{display:table-cell}
body.strong tr[data-fok="0"]{display:none}.fbar{margin-top:6px}.fbar label.tg{margin-left:0;display:flex;gap:5px;align-items:center}
.fsc{display:inline-block;min-width:30px;padding:1px 6px;border-radius:6px;font-weight:600;text-align:center}
.fsc.hi{background:var(--upbg);color:var(--up)}.fsc.mid{background:var(--bg);color:var(--ink);border:1px solid var(--line)}
.fsc.lo{background:var(--downbg);color:var(--down)}.fsc.na{color:var(--mute)}.fsn{display:block;font-size:11px;color:var(--mute)}
td.fw{text-align:left;white-space:normal;min-width:190px;font-size:12.5px}td.fw summary{cursor:pointer;color:var(--accent)}
td.fw ul{margin:6px 0 0;padding:0;list-style:none}td.fw li{margin:2px 0}td.fw li.ok{color:var(--up)}td.fw li.no{color:var(--down)}
td.fw li.na{color:var(--mute)}
a.kite{color:inherit;text-decoration:none}a.kite:hover{color:var(--accent);text-decoration:underline}
a.kite::after{content:"↗";font-size:10px;color:var(--mute);margin-left:2px;font-weight:400}
.bar.top{margin-bottom:10px}label.pick{display:flex;gap:8px;align-items:center;font-size:13px;color:var(--mute);flex:1}
label.pick select{flex:1;max-width:420px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);
color:var(--ink);font:inherit;font-size:15px;font-weight:600}
details.sec{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-top:10px}
details.sec summary{padding:11px 14px;cursor:pointer;list-style:none;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
details.sec summary::-webkit-details-marker{display:none}details.sec summary::before{content:"▸";color:var(--mute)}
details.sec[open] summary::before{content:"▾"}details.sec summary i{font-style:normal;color:var(--mute)}
details.sec summary p{margin:0;color:var(--mute);font-size:12.5px;flex-basis:100%;display:none}details.sec[open] summary p{display:block}
.x{display:none}body.allcols .x{display:table-cell}td.why{white-space:normal;min-width:200px;max-width:300px;text-align:left;color:var(--mute);font-size:12.5px}
.segs{display:flex;gap:4px}
.ipowin{display:flex;gap:6px;align-items:center;margin-top:8px!important;font-size:12.5px;color:var(--mute)}
.ipowin button{padding:4px 10px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--ink);font:inherit;cursor:pointer}
.ipowin button.on{background:var(--accent);border-color:var(--accent);color:var(--bg)}
tr.hide2{display:none}h2 i.cnt{font-style:normal;font-weight:400;color:var(--mute);font-size:14px}.segs button{padding:5px 10px;border:1px solid var(--line);border-radius:999px;
background:var(--card);color:var(--ink);font:inherit;font-size:13px;cursor:pointer}
.segs button.on{background:var(--accent);border-color:var(--accent);color:var(--bg)}tr.hide{display:none}
"""

JS = """
function recount(){document.querySelectorAll('.pane').forEach(p=>{const c=p.querySelector('h2 i.cnt');if(!c)return;
 const n=[...p.querySelectorAll('tbody tr')].filter(r=>getComputedStyle(r).display!=='none').length;c.textContent=n;
 const o=document.querySelector('#screen option[value="'+p.id.slice(5)+'"]');if(o)o.textContent=o.textContent.replace(/\(\d+\)$/,'('+n+')');});
 const h=document.getElementById('fhint');if(h)h.textContent=document.body.classList.contains('strong')
  ?'Hiding stocks that fail the check or have too little data. Click the Fundamentals entry on a row for the reasons.':'';}
['fscore','fstrong'].forEach(id=>{const el=document.getElementById(id);if(!el)return;const cls=id==='fscore'?'showscore':'strong';
 try{el.checked=localStorage.getItem(id)==='1'}catch(e){}document.body.classList.toggle(cls,el.checked);
 el.addEventListener('change',()=>{document.body.classList.toggle(cls,el.checked);try{localStorage.setItem(id,el.checked?'1':'0')}catch(e){};recount()});});
window.addEventListener('load',recount);
document.querySelectorAll('.ipowin button').forEach(b=>b.addEventListener('click',()=>{
 const sec=b.closest('section');sec.querySelectorAll('.ipowin button').forEach(x=>x.classList.toggle('on',x===b));
 const m=+b.dataset.m;let n=0;sec.querySelectorAll('tbody tr').forEach(r=>{const h=+r.dataset.age>m;r.classList.toggle('hide2',h);if(!h)n++});
 recount();}));
(()=>{const sel=document.getElementById('screen');if(!sel)return;
 const show=k=>{if(!document.getElementById('pane-'+k))return;sel.value=k;
  document.querySelectorAll('.pane').forEach(p=>p.classList.toggle('on',p.id==='pane-'+k))};
 let saved=null;try{saved=localStorage.getItem('screen')}catch(e){}
 show((location.hash||'').slice(1)||saved||sel.value);
 sel.addEventListener('change',()=>{show(sel.value);try{localStorage.setItem('screen',sel.value)}catch(e){};history.replaceState(null,'','#'+sel.value)});})();
document.getElementById('allcols')?.addEventListener('change',e=>document.body.classList.toggle('allcols',e.target.checked));
document.querySelectorAll('.segs button').forEach(b=>b.addEventListener('click',()=>{
 document.querySelectorAll('.segs button').forEach(x=>x.classList.toggle('on',x===b));const s=b.dataset.seg;
 document.querySelectorAll('tbody tr').forEach(r=>r.classList.toggle('hide',s!=='All'&&r.dataset.seg!==s));recount();}));
document.querySelectorAll('th').forEach(th=>th.addEventListener('click',()=>{
 const tb=th.closest('table').tBodies[0],i=th.cellIndex,asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
 [...tb.rows].sort((a,b)=>{const x=a.cells[i].dataset.v,y=b.cells[i].dataset.v,nx=parseFloat(x),ny=parseFloat(y);
  const c=isNaN(nx)||isNaN(ny)?x.localeCompare(y):nx-ny;return asc?c:-c}).forEach(r=>tb.appendChild(r));}));
"""


def _spark(series: pd.Series, level: Optional[float], tone: str) -> str:
    s = series.dropna().tail(60)
    if len(s) < 2:
        return ""
    w, h = 110, 28
    lo, hi = float(s.min()), float(s.max())
    if level is not None and not pd.isna(level):
        lo, hi = min(lo, level), max(hi, level)
    rng = (hi - lo) or 1.0
    y = lambda v: h - 2 - (v - lo) / rng * (h - 4)  # noqa: E731
    pts = " ".join(f"{i * w / (len(s) - 1):.1f},{y(v):.1f}" for i, v in enumerate(s))
    line = ""
    if level is not None and not pd.isna(level):
        line = (f'<line x1="0" x2="{w}" y1="{y(level):.1f}" y2="{y(level):.1f}" '
                f'stroke="var(--mute)" stroke-dasharray="3 3" stroke-width="1"/>')
    return (f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}">{line}'
            f'<polyline points="{pts}" fill="none" stroke="var(--{tone})" stroke-width="1.5"/></svg>')


def _candles(bars: Dict[str, pd.DataFrame], sym: str, n: int, level: float) -> str:
    df = pd.DataFrame({k: bars[k][sym] for k in ("open", "high", "low", "close")}).dropna().tail(n)
    if len(df) < 2:
        return ""
    w, h = 180, 60
    lo, hi = float(df["low"].min()), float(df["high"].max())
    if not pd.isna(level):
        lo, hi = min(lo, level), max(hi, level)
    rng = (hi - lo) or 1.0
    y = lambda v: h - 2 - (v - lo) / rng * (h - 4)  # noqa: E731
    step = w / len(df)
    bw = max(step * 0.62, 1.0)
    parts = []
    if not pd.isna(level):
        parts.append(f'<line x1="0" x2="{w}" y1="{y(level):.1f}" y2="{y(level):.1f}" '
                     f'stroke="var(--mute)" stroke-dasharray="3 3" stroke-width="1"/>')
    for i, (o, hh, ll, c) in enumerate(df.to_numpy()):
        x = (i + 0.5) * step
        col = "var(--up)" if c >= o else "var(--down)"
        top, bot = y(max(o, c)), y(min(o, c))
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y(hh):.1f}" y2="{y(ll):.1f}" stroke="{col}" stroke-width="1"/>'
                     f'<rect x="{x - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(bot - top, 0.8):.1f}" fill="{col}"/>')
    return f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}">{"".join(parts)}</svg>'


def kite_link(sym: str, token, exchange: str = "NSE") -> str:
    """The symbol as a link to its chart in Zerodha Kite (opens in a new tab)."""
    if token is None or token != token:  # missing or NaN
        return html.escape(sym)
    url = f"https://kite.zerodha.com/chart/ext/tvc/{exchange}/{urllib.parse.quote(sym, safe='')}/{int(token)}"
    return (f'<a class="kite" href="{html.escape(url)}" target="_blank" rel="noopener" '
            f'title="Open {html.escape(sym)} chart in Zerodha Kite">{html.escape(sym)}</a>')


def _fund_cells(f: Optional[dict]) -> Tuple[str, str, str]:
    """(score cell, logic cell, row flag) for one stock's fundamentals."""
    if not f or f["score"] is None:
        score = '<td class="fs" data-v="-1"><span class="fsc na">–</span></td>'
        logic = '<td class="fw" data-v="">No data</td>'
        return score, logic, "0"
    band = "hi" if f["score"] >= 67 else "mid" if f["score"] >= 50 else "lo"
    score = (f'<td class="fs" data-v="{f["score"]}"><span class="fsc {band}" title="{html.escape(f["summary"])}">'
             f'{f["score"]}</span><span class="fsn">{f["passed"]}/{f["counted"]}</span></td>')
    items = "".join(
        f'<li class="{"ok" if ok else "no" if ok is False else "na"}">{"✓" if ok else "✗" if ok is False else "–"} '
        f'{html.escape(name)}: {html.escape(detail)}</li>' for name, ok, detail in f["checks"])
    logic = (f'<td class="fw" data-v="{f["score"]}"><details><summary>{html.escape(f["summary"])}</summary>'
             f'<ul>{items}</ul></details></td>')
    return score, logic, "1" if f["strong"] else "0"


def _table(s: dict, uni: pd.DataFrame, prices: Dict[str, pd.DataFrame], weekly: Dict[str, pd.DataFrame],
           fund: Optional[Dict[str, dict]] = None) -> str:
    fund = fund or {}
    close = prices["close"]
    tokens = uni["kite_token"] if "kite_token" in uni.columns else pd.Series(dtype=float)
    df = s["df"]
    if df.empty:
        return f'<div class="empty">{html.escape(s.get("empty", "No stocks match today."))}</div>'
    level_key = next((k for k, *_ in s["cols"] if k.endswith("_level")), None)
    vol_key = level_key.replace("_level", "_vol_ok") if level_key else None
    charts = s.get("charts")
    extra = s.get("extra", set())
    x = lambda h: ' class="x"' if h in extra else ""  # noqa: E731
    head = ("<th>Stock</th>" + ("<th>Daily (60 days)</th><th>Weekly (52 weeks)</th>" if charts else "<th>60D</th>")
            + '<th class="fs" title="Fundamental score: share of the six checks passed (0-100)">Fund. score</th>'
            + '<th class="fw" title="Why this stock passes the fundamentals filter; click to see each check">Fundamentals</th>') + "".join(
        f'<th{x(h)} title="{html.escape(tip)}">{html.escape(h)}</th>' for _, h, _, tip in s["cols"])
    rows = []
    for sym, r in df.iterrows():
        name = uni["name"].get(sym, "")
        ind = uni["industry"].get(sym, "")
        dot = ' <span class="dot" title="Volume confirmed">●</span>' if vol_key and r[vol_key] else ""
        cells = [
            f'<td data-v="{html.escape(sym)}"><b>{kite_link(sym, tokens.get(sym))}{dot}</b>'
            f'<small title="{html.escape(name)}">{html.escape(ind)}</small></td>',
        ]
        if charts:
            side = s["side"]
            cells.append(f'<td data-v="0">{_candles(prices, sym, 60, r[f"{side}_level"])}</td>')
            cells.append(f'<td data-v="0">{_candles(weekly, sym, 52, r[f"{side}_wk_level"])}</td>')
        else:
            cells.append(f'<td data-v="0">{_spark(close[sym], r[level_key] if level_key else None, s["tone"])}</td>')
        fs_cell, fw_cell, strong = _fund_cells(fund.get(sym))
        cells += [fs_cell, fw_cell]
        for key, h, f, _ in s["cols"]:
            v = r[key]
            txt = _fmt(v, f)
            cls = ["x"] if h in extra else []
            if "+" in f and isinstance(v, (int, float)) and not pd.isna(v):
                cls.append("pos" if v > 0 else "neg" if v < 0 else "")
            if key == "why":
                cls.append("why")
            if h == "Score" and txt != "–":
                txt = f'<span class="score">{txt}</span>'
            attr = f' class="{" ".join(c for c in cls if c)}"' if any(cls) else ""
            cells.append(f'<td{attr} data-v="{html.escape(str(v))}">{html.escape(txt) if key == "why" else txt}</td>')
        age = f' data-age="{r["ipo_months"]}"' if s.get("ipo_filter") else ""
        rows.append(f'<tr data-seg="{html.escape(str(r.get("segment", "")))}" data-fok="{strong}"{age}>'
                    + "".join(cells) + "</tr>")
    return (f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def render_html(
    sections: List[dict],
    uni: pd.DataFrame,
    prices: Dict[str, pd.DataFrame],
    breadth: Dict[str, float],
    asof: pd.Timestamp,
    index_line: str,
    warning: str,
    skipped: List[str],
    note: str = "",
    fund: Optional[Dict[str, dict]] = None,
) -> str:
    from .signals import weekly_bars
    weekly = weekly_bars({k: prices[k] for k in ("open", "high", "low", "close", "volume")})
    stats = (f"<b>{breadth['above_50']:.0f}%</b> above 50-DMA · <b>{breadth['above_200']:.0f}%</b> above 200-DMA · "
             f"<b>{breadth['advancers']}</b> up / <b>{breadth['decliners']}</b> down · "
             f"<b>{breadth['near_high']}</b> near 52W high / <b>{breadth['near_low']}</b> near 52W low")

    def block(s: dict) -> str:
        table = _table(s, uni, prices, weekly, fund)
        toggle = ('<p class="ipowin">IPO in the last <button data-m="6">6 months</button>'
                  '<button data-m="12" class="on">12 months</button></p>' if s.get("ipo_filter") else "")
        on = " on" if s["key"] == default else ""
        return (f'<div class="pane{on}" id="pane-{s["key"]}" data-dir="{s["tab"]}">'
                f'<section id="{s["key"]}" class="{s["tone"]}"><header><h2>{s["title"]} '
                f'<i class="cnt">{len(s["df"])}</i></h2>'
                f'<p>{html.escape(s["note"])}</p>{toggle}</header>{table}</section></div>')

    # One picker lists every screener, grouped; the chosen one is shown.
    default = sections[0]["key"]
    groups = (("long", "Long"), ("short", "Short"), ("screens", "All-time highs"))
    opts = ""
    for tab, label in groups:
        secs = [s for s in sections if s["tab"] == tab]
        if secs:
            opts += f'<optgroup label="{label}">' + "".join(
                f'<option value="{s["key"]}"{" selected" if s["key"] == default else ""}>'
                f'{html.escape(s["title"])} ({len(s["df"])})</option>' for s in secs) + "</optgroup>"
    picker = f'<label class="pick">Screener <select id="screen">{opts}</select></label>'
    panes = "".join(block(s) for s in sections)
    segs = "".join(f'<button data-seg="{x}"{" class=on" if x == "All" else ""}>{x}</button>'
                   for x in ("All", "Large", "Mid", "Small", "Micro", "Other"))
    warn = f'<p class="warn">{html.escape(warning)}</p>' if warning else ""
    skip = (f" {len(skipped)} stocks were skipped (under 200 days of history, no data, or below the turnover floor)."
            if skipped else "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>NSE Breakout &amp; Momentum Scanner – {asof:%d %b %Y}</title>
<style>{CSS}</style></head><body><main>
<h1>NSE Breakout &amp; Momentum Scanner</h1>
<p class="sub">Data as of {asof:%a %d %b %Y} · {breadth['n']} stocks scanned{(' · ' + html.escape(index_line)) if index_line else ''}</p>
<p class="stats">{stats}</p>{warn}{('<p class="sub">' + html.escape(note) + '</p>') if note else ''}
<div class="bar top">{picker}</div>
<div class="bar"><span>Cap:</span><span class="segs">{segs}</span><label><input type="checkbox" id="allcols"> More columns</label></div>
<div class="bar fbar"><span>Fundamentals:</span><label class="tg"><input type="checkbox" id="fscore"> Show score</label>
<label class="tg"><input type="checkbox" id="fstrong"> Only fundamentally strong</label>
<span class="hint" id="fhint"></span></div>
{panes}
<footer>Daily bars from Yahoo Finance, adjusted for splits and dividends. Click a section to expand it and a column header to sort; hover a header for its definition.
The dashed line on each chart is the level being tested.{skip}<br>
This is a technical screen, not investment advice. Scores rank setups by rule-based criteria and say nothing about outcomes.</footer>
</main><script>{JS}</script></body></html>"""
