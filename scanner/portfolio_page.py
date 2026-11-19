"""The Portfolio page served by app.py at /portfolio.

Lists every holding and open position in the Zerodha account and, for each one
without an active GTT, proposes a stop-loss + target GTT sized from the
calculator's capital, risk % and reward : risk:

    risk amount   = capital x risk %
    stop distance = risk amount / quantity        (so hitting the stop loses the risk amount)
    stop          = basis -/+ stop distance        (basis = buy price or current price)
    target        = basis +/- reward:risk x stop distance

Nothing is placed without the reader confirming it.
"""
from __future__ import annotations

CSS = """
.rules{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;align-items:end}
.rules label{display:block;font-size:12.5px;color:var(--mute);margin-bottom:4px}
.rules input,.rules select{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-top:14px}
.card h2{margin:0 0 10px}.hint{font-size:12.5px;color:var(--mute)}
.banner{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:12px 14px;border-radius:10px;margin-top:14px;
background:var(--downbg);color:var(--ink);border:1px solid var(--line)}.banner.ok{background:var(--upbg)}
.gbtn{padding:8px 13px;border:1px solid var(--accent);border-radius:8px;background:var(--accent);color:var(--bg);font:inherit;font-weight:600;cursor:pointer;white-space:nowrap}
.gbtn.go{background:var(--up);border-color:var(--up)}.gbtn.sec{background:none;color:var(--ink);border-color:var(--line)}
.gbtn:disabled{opacity:.5;cursor:default}
td.st{white-space:normal;min-width:180px;text-align:left;font-size:12.5px}td.st .ok{color:var(--up);font-weight:600}
td.st .bad{color:var(--down)}td .sub{display:block;color:var(--mute);font-size:11.5px}
tr.done td{opacity:.7}a.kite{color:inherit;text-decoration:none}a.kite:hover{color:var(--accent);text-decoration:underline}
a.kite::after{content:"↗";font-size:10px;color:var(--mute);margin-left:2px;font-weight:400}.pill{font-size:11px;padding:1px 6px;border-radius:6px;border:1px solid var(--line);color:var(--mute);margin-left:4px}
.confirm{margin-top:12px;border:1px solid var(--line);border-radius:10px;padding:12px}
"""

BODY = """
<main>
<h1>Portfolio &amp; GTT</h1>
<p class="sub">Your Zerodha holdings and open positions, with a stop-loss and target proposed for each one that has no GTT yet.</p>
<div id="gate" class="card" style="display:none"></div>
<div id="app" style="display:none">
 <div class="card">
  <h2>Your rules <span class="hint" style="font-weight:400">(shared with the calculator)</span></h2>
  <div class="rules">
   <div><label for="cap">Trading capital (₹)</label><input id="cap" type="number" min="0" step="1000"></div>
   <div><label for="risk">Risk per position (% of capital)</label><input id="risk" type="number" min="0" step="0.1"></div>
   <div><label for="rr">Reward : risk</label><input id="rr" type="number" min="0" step="0.5"></div>
   <div><label for="basis">Measure stop and target from</label><select id="basis">
     <option value="avg">My buy price</option><option value="ltp">Current price</option></select></div>
   <div><label for="buf">Stop limit buffer (%)</label><input id="buf" type="number" min="0" max="5" step="0.1" value="0.5"></div>
  </div>
  <p class="hint" id="acct" style="margin:10px 0 0"></p>
 </div>
 <div id="banner"></div>
 <div class="card" style="padding:0;overflow:hidden">
  <div class="scroll"><table id="tbl"><thead><tr>
   <th>Stock</th><th>Qty</th><th>Buy avg</th><th>Now</th><th>P&amp;L</th><th>Stop-loss</th><th>Target</th><th>Loss at stop</th><th>Status</th>
  </tr></thead><tbody></tbody></table></div>
 </div>
 <p class="hint" style="margin-top:10px">Prices shown before placing are rounded to the nearest paisa; Zerodha's tick size is applied when the
 order is reviewed. Intraday (MIS) positions cannot have a GTT. Brokerage, taxes and slippage are not included.</p>
</div>
</main>
"""

JS = r"""
(()=>{const $=id=>document.getElementById(id);let rows=[],cash=null;
const inr=v=>'₹'+Math.round(v).toLocaleString('en-IN');
const px=v=>'₹'+Number(v).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
const esc=t=>String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const KEYS={cap:'calc_cap',risk:'calc_risk',rr:'calc_rr',basis:'pf_basis',buf:'pf_buf'};
const DEF={cap:'500000',risk:'1',rr:'2',basis:'avg',buf:'0.5'};
for(const k in KEYS){let v=null;try{v=localStorage.getItem(KEYS[k])}catch(e){}$(k).value=v!==null?v:DEF[k]}
for(const k in KEYS)$(k).addEventListener('input',()=>{try{localStorage.setItem(KEYS[k],$(k).value)}catch(e){}render()});
const num=id=>{const v=parseFloat($(id).value);return isFinite(v)?v:NaN};

function plan(r){ // the proposed GTT for one row, or {why} if none can be proposed
  if(!r.gtt_ok)return{why:'Intraday (MIS) position: Zerodha GTT does not support these. Use a stop-loss order in Kite.'};
  if(r.gtts.length)return{why:'',covered:true};
  const cap=num('cap'),risk=num('risk'),rr=num('rr');
  if(!(cap>0&&risk>0&&rr>0))return{why:'Enter capital, risk % and reward : risk above.'};
  const side=r.qty>0?1:-1,q=Math.abs(r.qty),now=r.ltp||r.avg,ref=$('basis').value==='ltp'?now:r.avg;
  if(!(ref>0))return{why:'No price available for this position.'};
  const riskAmt=cap*risk/100,dist=riskAmt/q;
  const sl=Math.round((ref-side*dist)*100)/100,tg=Math.round((ref+side*rr*dist)*100)/100;
  if(sl<=0)return{why:'Your risk amount ('+inr(riskAmt)+') is more than this whole position could lose, so the stop works out at or below zero. Lower the risk %.'};
  if(side===1&&!(sl<now))return{why:'Already below your stop: '+px(now)+' now, stop would be '+px(sl)+'. Measuring from your buy price, this position has lost more than your risk amount. Switch to "Current price" or decide in Kite.',sl,tg};
  if(side===-1&&!(sl>now))return{why:'Already above your stop: '+px(now)+' now, stop would be '+px(sl)+'. Switch to "Current price" or decide in Kite.',sl,tg};
  if(side===1&&!(tg>now))return{why:'Already past your target ('+px(tg)+'). Switch to "Current price" to set a fresh one.',sl,tg};
  if(side===-1&&!(tg<now))return{why:'Already past your target ('+px(tg)+'). Switch to "Current price" to set a fresh one.',sl,tg};
  return{why:'',side,q,sl,tg,now,loss:q*Math.abs(now-sl),dpct:Math.abs(ref-sl)/ref*100,tpct:Math.abs(tg-ref)/ref*100};
}

function render(){
  const tb=$('tbl').tBodies[0];tb.innerHTML='';let open=[];
  rows.forEach((r,i)=>{const p=plan(r);r._plan=p;const tr=document.createElement('tr');if(r._done)tr.className='done';
    const pnl=(r.ltp-r.avg)*r.qty,side=r.qty>0?'Long':'Short';
    let st;
    if(r._done)st='<span class="ok">GTT placed (#'+esc(r._done)+')</span>';
    else if(p.covered)st='<span class="ok">Protected</span>'+r.gtts.map(g=>'<span class="sub">GTT #'+esc(g.id)+': '+g.triggers.map(px).join(' / ')
      +(g.qty&&g.qty!==Math.abs(r.qty)?' · covers '+g.qty+' of '+Math.abs(r.qty):'')+'</span>').join('');
    else if(p.why)st='<span class="bad">'+esc(p.why)+'</span>';
    else{st='<button class="gbtn" data-i="'+i+'">Place GTT</button>';open.push(i)}
    const name=r.token?'<a class="kite" target="_blank" rel="noopener" title="Open chart in Zerodha Kite" href="https://kite.zerodha.com/chart/ext/tvc/'
      +encodeURIComponent(r.exchange)+'/'+encodeURIComponent(r.symbol)+'/'+r.token+'">'+esc(r.symbol)+'</a>':esc(r.symbol);
    tr.innerHTML='<td><b>'+name+'</b><span class="sub">'+esc(r.exchange)+' · '+esc(r.product)+' · '+side+'</span></td>'
      +'<td>'+Math.abs(r.qty).toLocaleString('en-IN')+'</td><td>'+px(r.avg)+'</td><td>'+(r.ltp?px(r.ltp):'–')+'</td>'
      +'<td class="'+(pnl>=0?'pos':'neg')+'">'+(pnl>=0?'+':'−')+inr(Math.abs(pnl))+'</td>'
      +'<td>'+(p.sl?px(p.sl)+(p.dpct?'<span class="sub">'+(p.side===-1?'+':'−')+p.dpct.toFixed(1)+'%</span>':''):'–')+'</td>'
      +'<td>'+(p.tg?px(p.tg)+(p.tpct?'<span class="sub">'+(p.side===-1?'−':'+')+p.tpct.toFixed(1)+'%</span>':''):'–')+'</td>'
      +'<td>'+(p.loss!==undefined?inr(p.loss)+'<span class="sub">from now</span>':'–')+'</td>'
      +'<td class="st">'+st+'</td>';
    tb.appendChild(tr)});
  tb.querySelectorAll('button[data-i]').forEach(b=>b.addEventListener('click',()=>review([+b.dataset.i])));
  const covered=rows.filter(r=>r._plan.covered||r._done).length;
  $('banner').innerHTML=open.length
    ?'<div class="banner"><b>'+open.length+' position'+(open.length>1?'s have':' has')+' no GTT.</b>'
      +'<span class="hint">Stop-loss and target are proposed below from your rules.</span>'
      +'<button class="gbtn" id="all">Review all '+open.length+'</button></div>'
    :rows.length?'<div class="banner ok"><b>'+covered+' of '+rows.length+' positions are protected by a GTT.</b>'
      +(rows.length>covered?'<span class="hint">The rest need attention: see the Status column.</span>':'')+'</div>':'';
  if(open.length)$('all').addEventListener('click',()=>review(open));
}

async function post(r,p,confirm){
  const res=await fetch('/api/kite/gtt',{method:'POST',headers:{'X-Scanner':'1','Content-Type':'application/json'},
    body:JSON.stringify({symbol:r.symbol,exchange:r.exchange,product:r.product,side:p.side,qty:p.q,stop:p.sl,target:p.tg,
      entry:r.avg,ltp:r.ltp,buffer_pct:num('buf')||0,confirm})});
  return res.json()}

async function review(idx){
  $('banner').innerHTML='<div class="banner"><span class="hint">Checking '+idx.length+' with Zerodha…</span></div>';
  const tickets=[];
  for(const i of idx){const r=rows[i];let t;try{t=await post(r,r._plan,false)}catch(e){t={error:'Could not reach the scanner.'}}tickets.push([i,t])}
  const ok=tickets.filter(([,t])=>!t.error);
  const line=([i,t])=>{const r=rows[i];if(t.error)return'<tr><td><b>'+esc(r.symbol)+'</b></td><td colspan="4" class="st"><span class="bad">'+esc(t.error)+'</span></td></tr>';
    return'<tr><td><b>'+esc(t.symbol)+'</b><span class="sub">'+(t.side===1?'SELL':'BUY')+' '+t.qty+' · '+esc(t.product)+'</span></td>'
     +'<td>'+px(t.sl_trigger)+'<span class="sub">limit '+px(t.sl_limit)+'</span></td>'
     +'<td>'+px(t.tgt_trigger)+'<span class="sub">limit '+px(t.tgt_limit)+'</span></td>'
     +'<td>'+px(t.ltp)+'<span class="sub">'+(t.ltp_live?'live':'last close')+'</span></td></tr>'};
  $('banner').innerHTML='<div class="card confirm"><h2>Confirm '+ok.length+' GTT'+(ok.length===1?'':'s')+'</h2>'
    +'<div class="scroll"><table><thead><tr><th>Stock</th><th>Stop trigger</th><th>Target trigger</th><th>Price now</th></tr></thead><tbody>'
    +tickets.map(line).join('')+'</tbody></table></div>'
    +'<p class="hint">When either trigger is reached, Zerodha places that limit order and cancels the other. Nothing is sent until you press Place.</p>'
    +(ok.length?'<button class="gbtn go" id="go">Place '+ok.length+' in Zerodha</button> ':'')+'<button class="gbtn sec" id="no">Cancel</button></div>';
  $('no').addEventListener('click',render);
  if(ok.length)$('go').addEventListener('click',async()=>{$('go').disabled=true;$('go').textContent='Placing…';const fails=[];
    for(const [i] of ok){const r=rows[i];let p;try{p=await post(r,r._plan,true)}catch(e){p={error:'Could not reach the scanner; check Kite in case it was placed.'}}
      if(p.error)fails.push(r.symbol+': '+p.error);else r._done=p.trigger_id}
    render();if(fails.length)$('banner').insertAdjacentHTML('afterbegin','<p class="msg">'+fails.map(esc).join('<br>')+'</p>')});
}

function gate(html){$('gate').style.display='';$('gate').innerHTML=html}
fetch('/api/kite/status').then(r=>r.json()).then(s=>{
  if(!s.local)return gate('Your Zerodha portfolio is only available on the Mac that runs the scanner, not from another device.');
  if(!s.configured)return gate('Zerodha is not set up yet. Create a Kite Connect app at developers.kite.trade with the redirect URL <b>'
    +esc(location.origin)+'/kite/callback</b>, put its api_key and api_secret into <b>data/kite.json</b>, then reload.');
  if(!s.connected)return gate('<a class="gbtn" style="text-decoration:none;display:inline-block" href="/kite/login?back=/portfolio">Connect to Zerodha</a> '
    +'<span class="hint">You log in on Zerodha\'s own page. Needed once each trading day.</span>');
  return fetch('/api/kite/portfolio').then(r=>r.json()).then(d=>{
    if(d.error)return gate('<p class="msg">'+esc(d.error)+'</p>');
    rows=d.rows;cash=d.cash;$('app').style.display='';
    const hv=rows.filter(r=>r.product==='CNC').reduce((a,r)=>a+r.value,0);
    $('acct').innerHTML='Connected as '+esc(s.user)+'. Holdings worth '+inr(hv)+(cash!==null?' · equity funds '+inr(cash)
      +' · <a href="#" id="usecap">use '+inr(hv+cash)+' as capital</a>':'')+'.';
    $('usecap')?.addEventListener('click',e=>{e.preventDefault();$('cap').value=Math.round(hv+cash);$('cap').dispatchEvent(new Event('input'))});
    if(!rows.length)return gate('No holdings or open positions in this account.');
    render()})
}).catch(()=>gate('Could not reach the scanner.'));
})();
"""
