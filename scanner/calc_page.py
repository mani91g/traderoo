"""The stop-loss / target calculator page served by app.py at /calc.

All arithmetic runs in the browser. Two ways to use it:
* "From my stop"      - you choose where the stop goes; it sizes the position so
                        that hitting the stop loses exactly your risk amount.
* "From my position"  - you choose how much to buy; it places the stop where
                        the loss equals your risk amount.
The target is always entry +/- (reward:risk x stop distance).
"""
from __future__ import annotations

CSS = """
.calc{display:grid;grid-template-columns:minmax(280px,380px) 1fr;gap:16px;align-items:start}
@media(max-width:760px){.calc{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.card h2{margin:0 0 10px}.f{margin-bottom:12px}.f label{display:block;font-size:12.5px;color:var(--mute);margin-bottom:4px}
.f input,.f select{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
.row{display:flex;gap:8px}.row>*{flex:1}.row>.u{flex:0 0 130px}
.seg2{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg2 button{flex:1;padding:8px;border:0;background:var(--bg);color:var(--ink);font:inherit;cursor:pointer}
.seg2 button.on{background:var(--accent);color:var(--bg);font-weight:600}
.hint{font-size:12px;color:var(--mute);margin-top:4px}
.big{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}
@media(max-width:520px){.big{grid-template-columns:1fr}}
.big div{border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.big span{display:block;font-size:12px;color:var(--mute)}.big b{font-size:22px;font-variant-numeric:tabular-nums}
.big .sl b{color:var(--down)}.big .tg b{color:var(--up)}.big small{display:block;color:var(--mute);font-size:12px}
table.kv{width:100%;border-collapse:collapse}table.kv td{padding:7px 0;border-top:1px solid var(--line);text-align:left;white-space:normal}
table.kv td:last-child{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.scale{position:relative;height:46px;margin:6px 0 16px}.scale .bar{position:absolute;top:20px;left:0;right:0;height:8px;border-radius:4px;display:flex;overflow:hidden}
.scale .bar i{display:block;height:100%}.scale .r{background:var(--down)}.scale .w{background:var(--up)}
.scale span{position:absolute;top:0;font-size:11.5px;color:var(--mute);transform:translateX(-50%);white-space:nowrap}
.scale span.a{transform:none;left:0}.scale span.z{transform:none;right:0;left:auto}
.scale u{position:absolute;top:16px;width:2px;height:16px;background:var(--ink);text-decoration:none}
.gtt{margin-top:16px;padding-top:14px;border-top:1px solid var(--line)}
.gbtn{padding:9px 14px;border:1px solid var(--accent);border-radius:8px;background:var(--accent);color:var(--bg);font:inherit;font-weight:600;cursor:pointer}
.gbtn.go{background:var(--up);border-color:var(--up)}.gbtn.sec{background:none;color:var(--ink);border-color:var(--line)}.gbtn:disabled{opacity:.5;cursor:default}
.ticket{margin-top:12px;border:1px solid var(--line);border-radius:10px;padding:12px}.ticket table{margin-bottom:10px}
.ticket .ok{color:var(--up);font-weight:600}
.msg{margin:0 0 8px;padding:8px 10px;border-radius:8px;font-size:13px;background:var(--downbg);color:var(--down)}
.msg.note{background:var(--upbg);color:var(--ink)}
"""

BODY = """
<main>
<h1>Stop-loss &amp; target calculator</h1>
<p class="sub">Sizes a trade from the share of capital you are willing to lose and your reward-to-risk ratio.</p>
<div class="calc">
 <div class="card">
  <h2>Your rules</h2>
  <div class="f"><label for="cap">Trading capital (₹)</label><input id="cap" type="number" min="0" step="1000" value="500000"></div>
  <div class="row">
   <div class="f"><label for="risk">Risk per trade (% of capital)</label><input id="risk" type="number" min="0" step="0.1" value="1"></div>
   <div class="f"><label for="rr">Reward : risk</label><input id="rr" type="number" min="0" step="0.5" value="2"></div>
  </div>
  <h2 style="margin-top:6px">The trade</h2>
  <div class="f"><label>Direction</label><div class="seg2" id="dir"><button data-v="1" class="on">Long</button><button data-v="-1">Short</button></div></div>
  <div class="f"><label for="entry">Entry price (₹)</label><input id="entry" type="number" min="0" step="0.05">
   <div class="hint" id="syminfo"></div></div>
  <div class="f"><label>Work it out</label><div class="seg2" id="mode"><button data-v="stop" class="on">From my stop</button><button data-v="size">From my position</button></div></div>
  <div class="f" id="f-stop"><label for="stopv">Stop-loss</label>
   <div class="row"><input id="stopv" type="number" min="0" step="0.05" value="5">
   <select id="stopu" class="u"><option value="pct">% away</option><option value="price">₹ price</option><option value="atr">× ATR away</option></select></div>
   <div class="hint">The position is sized so that hitting this stop loses your risk amount.</div>
   <div id="f-atr" style="display:none;margin-top:10px"><label for="atr">ATR (% of price): the stock's average daily range</label>
   <input id="atr" type="number" min="0" step="0.1" placeholder="e.g. 3.5"></div></div>
  <div class="f" id="f-size" style="display:none"><label for="sizev">Position size</label>
   <div class="row"><input id="sizev" type="number" min="0" step="1" value="100000">
   <select id="sizeu" class="u"><option value="amt">₹ invested</option><option value="qty">shares</option></select></div>
   <div class="hint">The stop is placed where the loss on this position equals your risk amount.</div></div>
 </div>
 <div class="card">
  <h2>Result</h2>
  <div id="msgs"></div>
  <div class="big">
   <div class="sl"><span>Stop-loss</span><b id="o-sl">–</b><small id="o-sld"></small></div>
   <div><span>Entry</span><b id="o-en">–</b><small id="o-qty"></small></div>
   <div class="tg"><span>Target</span><b id="o-tg">–</b><small id="o-tgd"></small></div>
  </div>
  <div class="scale" id="scale"></div>
  <table class="kv">
   <tr><td>Quantity</td><td id="k-qty">–</td></tr>
   <tr><td>Position value</td><td id="k-pos">–</td></tr>
   <tr><td>Loss if the stop is hit</td><td id="k-loss">–</td></tr>
   <tr><td>Profit if the target is hit</td><td id="k-gain">–</td></tr>
   <tr><td>Stop distance</td><td id="k-dist">–</td></tr>
   <tr><td>Win rate needed to break even</td><td id="k-be">–</td></tr>
  </table>
  <p class="hint">Prices are rounded to paise and quantity is rounded down to whole shares, so the loss at the stop can be slightly
  under your risk amount. Brokerage, taxes and slippage are not included.</p>
  <div class="gtt" id="gtt">
   <h2>Place in Zerodha</h2>
   <p class="hint" style="margin:0 0 10px">Sets the stop-loss and target above as one GTT on shares you already hold: when either
   price is reached Zerodha places a sell order and cancels the other. It does not buy the shares.</p>
   <div id="gtt-off" class="hint"></div>
   <div id="gtt-on" style="display:none">
    <div class="row">
     <div class="f"><label for="gsym">NSE symbol</label><input id="gsym" placeholder="e.g. INFY" autocapitalize="characters" autocomplete="off"></div>
     <div class="f"><label for="gbuf">Stop limit buffer (%)</label><input id="gbuf" type="number" min="0" max="5" step="0.1" value="0.5"></div>
    </div>
    <div class="hint" style="margin:-6px 0 10px">The stop's sell order is a limit order this far below its trigger, so it can still fill while the price is falling.</div>
    <button id="grev" class="gbtn">Review GTT</button> <span class="hint" id="guser"></span>
    <div id="gbox"></div>
   </div>
  </div>
 </div>
</div>
</main>
"""

JS = r"""
(()=>{const $=id=>document.getElementById(id);let stocks={},dir=1,mode='stop';
const inr=v=>'₹'+v.toLocaleString('en-IN',{maximumFractionDigits:0});
const px=v=>'₹'+v.toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
const num=id=>{const v=parseFloat($(id).value);return isFinite(v)?v:NaN};
const KEEP=['cap','risk','rr'];
try{KEEP.forEach(k=>{const v=localStorage.getItem('calc_'+k);if(v!==null)$(k).value=v})}catch(e){}
function seg(id,cb){$(id).querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{
  $(id).querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));cb(b.dataset.v);calc()}))}
seg('dir',v=>dir=+v);
seg('mode',v=>{mode=v;$('f-stop').style.display=v==='stop'?'':'none';$('f-size').style.display=v==='size'?'':'none'});
$('stopu').addEventListener('change',()=>{$('f-atr').style.display=$('stopu').value==='atr'?'':'none'});
document.querySelectorAll('input,select').forEach(e=>e.addEventListener('input',calc));
function show(o){for(const k in o)$(k).textContent=o[k]}
function calc(){
  try{KEEP.forEach(k=>localStorage.setItem('calc_'+k,$(k).value))}catch(e){}
  const cap=num('cap'),risk=num('risk'),rr=num('rr'),entry=num('entry'),atr=num('atr'),msgs=[],notes=[];
  const blank={'o-sl':'–','o-en':'–','o-tg':'–','o-sld':'','o-qty':'','o-tgd':'','k-qty':'–','k-pos':'–','k-loss':'–','k-gain':'–','k-dist':'–','k-be':'–'};
  const fail=m=>{window.CALC=null;document.dispatchEvent(new Event('calc'));show(blank);$('scale').innerHTML='';$('msgs').innerHTML=m?'<p class="msg">'+m+'</p>':''};
  if(!(cap>0&&risk>0&&rr>0))return fail('Enter your capital, risk per trade and reward : risk.');
  if(!(entry>0))return fail('Enter an entry price.');
  const riskAmt=cap*risk/100;let dist,qty;
  if(mode==='stop'){const v=num('stopv'),u=$('stopu').value;
    if(!(v>0))return fail('Enter a stop-loss.');
    if(u==='atr'){if(!(atr>0))return fail('An ATR-based stop needs the stock\'s ATR %. Enter it below the stop, or switch the stop to % or ₹.');dist=v*atr/100*entry}
    else if(u==='pct')dist=entry*v/100;
    else{dist=dir*(entry-v);if(!(dist>0))return fail('For a '+(dir===1?'long, the stop must be below':'short, the stop must be above')+' the entry price.')}
    qty=Math.floor(riskAmt/dist);
    if(qty<1)return fail('Your risk amount ('+inr(riskAmt)+') is smaller than the loss on a single share at this stop ('+px(dist)+').');
  }else{const v=num('sizev');if(!(v>0))return fail('Enter a position size.');
    qty=Math.floor($('sizeu').value==='qty'?v:v/entry);
    if(qty<1)return fail('That amount buys less than one share at this price.');
    dist=riskAmt/qty}
  const sl=Math.round((entry-dir*dist)*100)/100,tg=Math.round((entry+dir*rr*dist)*100)/100;
  if(sl<=0)return fail('This position is too small for your risk amount: even if the price fell to zero you would lose less than '+inr(riskAmt)+'. Increase the position or lower the risk %.');
  if(dir===-1&&tg<=0)return fail('The target works out below zero. Lower the reward : risk or tighten the stop.');
  const pos=qty*entry,loss=qty*Math.abs(entry-sl),gain=qty*Math.abs(tg-entry),dp=dist/entry*100;
  if(pos>cap)msgs.push('This position costs '+inr(pos)+', which is '+(pos/cap).toFixed(1)+'× your capital. Widen the stop or lower the risk %.');
  if(atr>0){const a=dist/(atr/100*entry);
    if(a<1)notes.push('The stop is '+a.toFixed(1)+' ATR from entry, inside a normal day\'s range for this stock.');}
  show({'o-sl':px(sl),'o-en':px(entry),'o-tg':px(tg),
    'o-sld':(dir===1?'−':'+')+dp.toFixed(1)+'% from entry','o-qty':qty.toLocaleString('en-IN')+' shares',
    'o-tgd':(dir===1?'+':'−')+(dp*rr).toFixed(1)+'% from entry',
    'k-qty':qty.toLocaleString('en-IN')+' shares','k-pos':inr(pos)+' ('+(pos/cap*100).toFixed(0)+'% of capital)',
    'k-loss':inr(loss)+' ('+(loss/cap*100).toFixed(2)+'% of capital)','k-gain':inr(gain)+' ('+(gain/cap*100).toFixed(2)+'% of capital)',
    'k-dist':px(dist)+' · '+dp.toFixed(1)+'%'+(atr>0?' · '+(dist/(atr/100*entry)).toFixed(1)+' ATR':''),
    'k-be':(100/(1+rr)).toFixed(0)+'%'});
  const w=100/(1+rr),L=dir===1?['Stop '+px(sl),'Target '+px(tg)]:['Target '+px(tg),'Stop '+px(sl)],e=dir===1?w:100-w;
  $('scale').innerHTML='<span class="a">'+L[0]+'</span><span style="left:'+e+'%">Entry</span><span class="z">'+L[1]+'</span>'
    +'<div class="bar">'+(dir===1?'<i class="r" style="width:'+w+'%"></i><i class="w" style="width:'+(100-w)+'%"></i>'
    :'<i class="w" style="width:'+(100-w)+'%"></i><i class="r" style="width:'+w+'%"></i>')+'</div><u style="left:calc('+e+'% - 1px)"></u>';
  window.CALC={dir,entry,sl,tg,qty};document.dispatchEvent(new Event('calc'));
  $('msgs').innerHTML=msgs.map(m=>'<p class="msg">'+m+'</p>').join('')+notes.map(m=>'<p class="msg note">'+m+'</p>').join('');
}
// Arriving from a scanner row (/calc?s=SYMBOL): fill in that stock's last close and ATR.
const q=new URLSearchParams(location.search),sym=(q.get('s')||'').toUpperCase();
if(q.get('d')==='short'){dir=-1;$('dir').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.v==='-1'))}
if(sym)fetch('/api/stocks').then(r=>r.json()).then(d=>{const s=d.stocks[sym];if(!s)return;
  $('entry').value=s.close.toFixed(2);if(s.atr_pct)$('atr').value=s.atr_pct.toFixed(1);
  $('syminfo').textContent='Filled in from '+sym+': last close '+px(s.close)+(s.atr_pct?', ATR '+s.atr_pct.toFixed(1)+'%':'')+'.';calc()}).catch(()=>{});
calc();})();
"""

KITE_JS = r"""
(()=>{const $=id=>document.getElementById(id),off=$('gtt-off'),on=$('gtt-on'),box=$('gbox'),rev=$('grev');
const px=v=>'₹'+Number(v).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
const esc=t=>String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const q=new URLSearchParams(location.search);if(q.get('s'))$('gsym').value=q.get('s').toUpperCase();
let connected=false;
function gate(){const c=window.CALC;box.innerHTML='';
  if(!connected)return;
  if(!c){rev.disabled=true;return}
  if(c.dir!==1){rev.disabled=true;box.innerHTML='<p class="hint">GTT placement is set up for long delivery positions only. Short positions are in futures, which this does not handle.</p>';return}
  rev.disabled=false}
document.addEventListener('calc',gate);
['gsym','gbuf'].forEach(i=>$(i).addEventListener('input',()=>{box.innerHTML=''}));
fetch('/api/kite/status').then(r=>r.json()).then(s=>{
  if(!s.local){off.textContent='Orders can only be placed from the Mac that runs the scanner, not from another device.';return}
  if(!s.configured){off.innerHTML='Not set up yet. Create a Kite Connect app at developers.kite.trade with the redirect URL <b>'
    +esc(location.origin)+'/kite/callback</b>, then put its api_key and api_secret into <b>data/kite.json</b> in the project folder and reload this page.';return}
  if(!s.connected){off.innerHTML='<a class="gbtn" style="text-decoration:none;display:inline-block" href="/kite/login">Connect to Zerodha</a>'
    +' <span class="hint">You log in on Zerodha\'s own page. Needed once each trading day.</span>';return}
  connected=true;off.style.display='none';on.style.display='';$('guser').textContent='Connected as '+s.user;gate()
}).catch(()=>{off.textContent='Could not check the Zerodha connection.'});
async function send(confirm){const c=window.CALC;
  const r=await fetch('/api/kite/gtt',{method:'POST',headers:{'X-Scanner':'1','Content-Type':'application/json'},
    body:JSON.stringify({symbol:$('gsym').value,qty:c.qty,stop:c.sl,target:c.tg,entry:c.entry,buffer_pct:parseFloat($('gbuf').value)||0,confirm})});
  return r.json()}
rev.addEventListener('click',async()=>{if(!window.CALC)return;rev.disabled=true;box.innerHTML='<p class="hint">Checking with Zerodha…</p>';
  let t;try{t=await send(false)}catch(e){t={error:'Could not reach the scanner.'}}
  rev.disabled=false;
  if(t.error){box.innerHTML='<p class="msg">'+esc(t.error)+'</p>';return}
  const hold=t.holding===null?'Could not read your holdings.':t.holding>=t.qty?'You hold '+t.holding+' shares.'
    :'You hold '+t.holding+' shares, fewer than this GTT sells. The sell order will be rejected when it triggers unless you hold enough by then.';
  box.innerHTML='<div class="ticket"><table class="kv">'
   +'<tr><td>Stock</td><td>NSE: '+esc(t.symbol)+'</td></tr>'
   +'<tr><td>Sell quantity</td><td>'+t.qty+' shares (delivery)</td></tr>'
   +'<tr><td>Stop-loss</td><td>trigger '+px(t.sl_trigger)+' → sell limit '+px(t.sl_limit)+'</td></tr>'
   +'<tr><td>Target</td><td>trigger '+px(t.tgt_trigger)+' → sell limit '+px(t.tgt_limit)+'</td></tr>'
   +'<tr><td>Current price used</td><td>'+px(t.ltp)+(t.ltp_live?' (live)':' (your entry price; live quotes not available on this API plan)')+'</td></tr>'
   +'</table><p class="'+(t.holding!==null&&t.holding<t.qty?'msg':'hint')+'">'+hold+'</p>'
   +'<button class="gbtn go" id="gplace">Place this GTT in Zerodha</button> <button class="gbtn sec" id="gcancel">Cancel</button></div>';
  $('gcancel').addEventListener('click',()=>{box.innerHTML=''});
  $('gplace').addEventListener('click',async()=>{$('gplace').disabled=true;$('gplace').textContent='Placing…';
    let p;try{p=await send(true)}catch(e){p={error:'Could not reach the scanner. Check Kite before trying again, in case the GTT was placed.'}}
    box.innerHTML=p.error?'<p class="msg">'+esc(p.error)+'</p>'
      :'<div class="ticket"><p class="ok">GTT placed. Zerodha trigger id '+esc(p.trigger_id)+'.</p><p class="hint">Check or change it in Kite under Orders → GTT.</p></div>'})});
})();
"""
