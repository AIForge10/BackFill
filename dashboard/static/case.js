// Charts render existing daily records only. No synthetic prices or backtest calls.
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = v => `${v >= 0 ? '+' : ''}${(v*100).toFixed(2)}%`;
const money = v => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:0}).format(v);
const names = {FMS:'FMS',ICUI:'ICUI',basket:'Beneficiary basket',SPY:'SPY'};
const colors = {FMS:'fms',ICUI:'icui',basket:'basket',SPY:'spy'};
let data;
const state = {mode:'net',vendor:'reference_mix',range:'trade',style:'line',costs:1,
  visible:new Set(['FMS','ICUI','basket','SPY'])};

function chart(container, points, keys, {style='line', readout, label, markers=true}={}) {
  if (!points.length || !keys.length) {
    container.innerHTML='<div class="empty-state"><strong>No series selected</strong><p>Select a series above to inspect its real daily records.</p></div>';
    if(readout)readout.textContent='';
    return;
  }
  const W=Math.max(320,Math.min(840,container.clientWidth||840)),H=280,L=50,R=15,T=35,B=42;
  const values=points.flatMap(p=>keys.map(k=>p[k])).filter(Number.isFinite);
  const min=Math.min(0,...values),max=Math.max(0,...values),pad=Math.max((max-min)*.14,.004);
  const low=min-pad,high=max+pad;
  const x=i=>L+(i+.5)/points.length*(W-L-R),y=v=>T+(high-v)/(high-low)*(H-T-B);
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" tabindex="0" aria-label="${esc(label)}. Arrow keys inspect actual sessions."><title>${esc(label)}</title>`;
  for(let i=0;i<5;i++) {
    const v=low+(high-low)*i/4;
    svg+=`<line class="chart-grid" x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"/><text class="chart-label" x="${L-8}" y="${y(v)+3}" text-anchor="end">${(v*100).toFixed(1)}%</text>`;
  }
  svg+=`<line class="chart-zero" x1="${L}" x2="${W-R}" y1="${y(0)}" y2="${y(0)}"/>`;
  const tickIndices=[...new Set([0,Math.round((points.length-1)/3),Math.round((points.length-1)*2/3),points.length-1])];
  for(const i of tickIndices)svg+=`<text class="chart-label" x="${x(i)}" y="${H-12}" text-anchor="middle">${esc(points[i].date.slice(5))}</text>`;
  if(markers)for(const [date,name] of [[data.case.announcement_date,'ANNOUNCEMENT'],[data.entry_date,'ENTRY'],[data.exit_date,'EXIT']]) {
    const i=points.findIndex(p=>p.date===date);
    if(i>=0)svg+=`<line class="case-marker-line" x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${H-B}"/><text class="chart-label" x="${x(i)}" y="17" text-anchor="middle">${name}</text>`;
  }
  keys.forEach((key,ki)=>{
    if(style==='bar') {
      const group=(W-L-R)/points.length*.72,bw=group/keys.length;
      points.forEach((p,i)=>{if(Number.isFinite(p[key]))svg+=`<rect class="case-bar ${colors[key]}" x="${x(i)-group/2+ki*bw}" y="${Math.min(y(0),y(p[key]))}" width="${Math.max(1,bw-1)}" height="${Math.max(.4,Math.abs(y(p[key])-y(0)))}"/>`;});
    }else{
      // Split at missing observations instead of drawing invented points across a gap.
      let segment=[];
      const flush=()=>{if(segment.length)svg+=`<polyline class="case-line ${colors[key]}" points="${segment.join(' ')}"/>`;segment=[];};
      points.forEach((p,i)=>{if(Number.isFinite(p[key]))segment.push(`${x(i)},${y(p[key])}`);else flush();});flush();
      points.forEach((p,i)=>{if(Number.isFinite(p[key]))svg+=`<circle class="case-dot ${colors[key]}" cx="${x(i)}" cy="${y(p[key])}" r="${points.length>12?1.7:3}"/>`;});
    }
  });
  svg+=`<line class="chart-zero case-cursor" x1="${L}" x2="${L}" y1="${T}" y2="${H-B}" visibility="hidden"/></svg>`;
  container.innerHTML=svg;
  const element=container.querySelector('svg'),cursor=element.querySelector('.case-cursor');
  let index=points.length-1;
  const inspect=i=>{
    index=Math.max(0,Math.min(points.length-1,i));
    cursor.setAttribute('visibility','visible');cursor.setAttribute('x1',x(index));cursor.setAttribute('x2',x(index));
    if(readout)readout.textContent=`${points[index].date} · ${keys.map(k=>`${names[k]} ${Number.isFinite(points[index][k])?pct(points[index][k]):'Unavailable'}`).join(' · ')}`;
  };
  element.addEventListener('pointermove',e=>{const box=element.getBoundingClientRect();inspect(Math.floor(((e.clientX-box.left)/box.width*W-L)/(W-L-R)*points.length));});
  element.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();inspect(index+(e.key==='ArrowLeft'?-1:1));}});
  inspect(points.length-1);cursor.setAttribute('visibility','hidden');
}

function renderMoney() {
  const capital=Number($('#case-capital').value),allocation=capital*.05;
  const rows=data.accounting[String(state.costs)].breakdown;
  const net=rows.find(r=>r.ticker==='basket').net;
  $('#case-capital-label').textContent=money(capital);
  $('#case-money').textContent=`${money(allocation/2)} in each beneficiary, with a combined short-SPY hedge of ${money(allocation*rows.find(r=>r.ticker==='basket').beta)}. Saved net outcome: ${money(allocation*net)}, or ${pct(.05*net)} of account capital.`;
}

function renderHedge() {
  const rows=data.accounting[String(state.costs)].breakdown;
  $('#hedge-breakdown').innerHTML=rows.map(r=>`<tr><td>${esc(names[r.ticker])}</td><td>${pct(r.stock)}</td><td>${pct(r.hedge)}</td><td>${pct(r.fees)}</td><td><strong>${pct(r.net)}</strong></td></tr>`).join('');
  const r=rows.find(r=>r.ticker==='basket');
  const components=[['Stock',0,r.stock,'ink'],['SPY hedge',r.stock,r.stock+r.hedge,'muted'],['Costs / carry',r.stock+r.hedge,r.net,'cool'],['Net hedged',0,r.net,'ember']];
  const W=540,H=200,L=46,T=25,B=36,low=Math.min(0,r.stock,r.net)-.004,high=Math.max(r.stock+r.hedge,r.net,0)+.004;
  const y=v=>T+(high-v)/(high-low)*(H-T-B);
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Basket return waterfall: stock return, SPY hedge, costs and net return"><line class="chart-zero" x1="${L}" x2="${W-15}" y1="${y(0)}" y2="${y(0)}"/>`;
  components.forEach(([label,start,end,color],i)=>{
    const x=L+i*120,delta=end-start;
    svg+=`<rect class="waterfall-bar ${color}" x="${x+15}" y="${Math.min(y(start),y(end))}" width="64" height="${Math.max(1,Math.abs(y(end)-y(start)))}"><title>${esc(label)}: ${pct(delta)}</title></rect><text class="chart-label" x="${x+47}" y="${Math.min(y(start),y(end))-8}" text-anchor="middle">${pct(delta)}</text><text class="chart-label" x="${x+47}" y="${H-13}" text-anchor="middle">${esc(label)}</text>`;
    if(i<2)svg+=`<line class="chart-zero" x1="${x+79}" x2="${x+135}" y1="${y(end)}" y2="${y(end)}"/>`;
  });
  $('#hedge-chart').innerHTML=svg+'</svg>';
  $('#case-net').textContent=pct(r.net);
  renderMoney();
}

function renderCase() {
  const prices=data.prices[state.vendor];
  const last=prices.points.find(r=>r.date===data.exit_date);
  $('#case-stock').textContent=pct(last.basket);
  const excess=(last.basket-last.SPY)*100;
  $('#case-excess').textContent=`${excess>=0?'+':''}${excess.toFixed(2)} pp`;
  renderHedge();
  $('#case-style').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.style===state.style)));
  $('#case-costs').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.cost)===state.costs)));
  const keys=(state.mode==='net'||state.mode==='excess'?['FMS','ICUI','basket']:['FMS','ICUI','basket','SPY']);
  $('#case-legend').innerHTML=keys.map(k=>`<button class="series-toggle ${colors[k]}" data-series="${k}" aria-pressed="${state.visible.has(k)}">${esc(names[k])}</button>`).join('');
  $('#case-legend').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{state.visible.has(b.dataset.series)?state.visible.delete(b.dataset.series):state.visible.add(b.dataset.series);renderCase();}));
  $('#case-chart-title').textContent={net:'Net beta-hedged movement',stock:'Actual stock movement versus SPY',excess:'Stock return minus SPY'}[state.mode];
  $('#case-chart-source').textContent=state.vendor==='webull_only'?'WEBULL / ACTUAL ADJUSTED DAILY BARS':'SAVED ACCOUNTING / FMS YAHOO FALLBACK';
  if(state.mode==='net'&&state.vendor==='webull_only') {
    $('#case-chart').innerHTML='<div class="empty-state"><strong>Webull-only net accounting is unavailable</strong><p>Select a stock view to inspect actual Webull movement, or the saved accounting source for the reconciled hedged result.</p></div>';
    $('#case-readout').textContent='No vendor is silently substituted.';
    $('#case-chart-note').textContent='The +1.06% saved basket result uses the recorded FMS Yahoo adjustment fallback.';
    return;
  }
  let points=state.mode==='net'?data.accounting[String(state.costs)].points:prices.points;
  if(state.mode==='excess')points=points.map(p=>({date:p.date,...Object.fromEntries(keys.map(k=>[k,p[k]-p.SPY]))}));
  if(state.range==='trade')points=points.filter(p=>p.date>=data.entry_date&&p.date<=data.exit_date);
  chart($('#case-chart'),points,keys.filter(k=>state.visible.has(k)),{style:state.style,readout:$('#case-readout'),label:$('#case-chart-title').textContent});
  $('#case-chart-note').textContent=state.mode==='net'?'Returns on invested stock capital; entry costs appear at entry. The SPY hedge is included. This curve is not the whole account return.':`Daily cumulative changes rebased to the November 11 entry close. ${state.mode==='excess'?'SPY subtraction is a simple benchmark difference, not beta-hedged P&L.':'Stock returns exclude hedges and modeled trading costs.'} ${state.vendor==='webull_only'?'All three instruments use verified Webull bars.':'FMS uses Yahoo; ICUI and SPY use Webull.'} Bars and lines show the same actual session observations.`;
}

export async function initCase() {
  try {
    const response=await fetch('/api/case',{cache:'no-store'});
    if(!response.ok)throw new Error('Saved case data unavailable.');
    data=await response.json();
    const timingNames={immediate_hold250:'Immediate / 250 sessions',registered_horizon:'Immediate / 60 sessions',wait20_hold5:'Delay 20 / hold 5 sessions'};
    $('#case-other-timings').innerHTML=(data.previously_inspected_timings??[]).map(r=>`<tr><td>${esc(timingNames[r.timing]??r.timing)}</td><td>${esc(r.buy_date)} → ${esc(r.sell_date)}</td><td>×${Number(r.cost_multiplier)}</td><td>${pct(Number(r.gross_stock_return))}</td><td>${pct(Number(r.net_lot_return))}</td></tr>`).join('');
    $('#case-eligibility').textContent=data.case.frozen_strategy_action.reason;
    const audit=data.case.strict_later_period_audit;
    $('#case-audit').innerHTML=[[audit.economic_events,'EVENTS AUDITED'],[audit.events_excluded_archive_gap,'ARCHIVE-GAP EXCLUSIONS'],[audit.eligible_lots,'ELIGIBLE TRADES']].map(([n,l])=>`<div><strong>${n}</strong><span>${l}</span></div>`).join('');
    const source=data.case.sources[0];
    if(source&&/^https:\/\//.test(source.url))$('#case-source').innerHTML=`<a class="text-link" target="_blank" rel="noopener" href="${esc(source.url)}">Read the supplier statement ↗</a>`;
    $('#case-provenance').innerHTML=`<p>Webull adjustment: ${esc(data.prices.webull_only.adjustments.webull.daily_bars)}. This chart uses the vendor's adjusted daily close; raw, licensed price files are not included in this download.</p>${Object.entries(data.prices).map(([policy,p])=>`<h4>${policy==='webull_only'?'Webull-only price chart':'Saved accounting price policy'}</h4>${Object.entries(p.provenance).map(([ticker,r])=>`<div class="hash-row"><div><span>${esc(ticker)} · ${esc(r.vendor)}</span><span>${esc(r.retrieved_at)}</span></div><code>${esc(r.sha256)}</code>${r.fallback_reason?`<p>${esc(r.fallback_reason)}</p>`:''}</div>`).join('')}`).join('')}<h4>Saved evidence and accounting files</h4>${data.sources.map(r=>`<div class="hash-row"><div><span>${esc(r.file)}</span></div><code>${esc(r.sha256)}</code></div>`).join('')}<p class="source-hash">Chart bundle SHA-256 ${esc(data.bundle_sha256)}</p>`;
    for(const [id,key]of [['case-mode','mode'],['case-vendor','vendor'],['case-range','range']])$('#'+id).addEventListener('change',e=>{state[key]=e.target.value;renderCase();});
    $('#case-style').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{state.style=b.dataset.style;renderCase();}));
    $('#case-costs').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{state.costs=Number(b.dataset.cost);renderCase();}));
    $('#case-capital').addEventListener('input',renderMoney);
    $('#reveal-case').addEventListener('click',()=>{
      const open=$('#case-outcome').hidden;
      $('#case-outcome').hidden=!open;$('#reveal-description').hidden=open;
      $('#reveal-case').setAttribute('aria-expanded',String(open));
      $('#reveal-case').textContent=open?'Hide saved movement ↑':'Reveal actual movement ↘';
      if(open)chart($('#outcome-chart'),data.accounting['1'].points.filter(p=>p.date>=data.entry_date&&p.date<=data.exit_date),['FMS','ICUI','basket'],{readout:$('#outcome-readout'),label:'Previously evaluated beneficiary net hedged movement'});
    });
    let resizeTimer;
    window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{
      renderCase();
      if(!$('#case-outcome').hidden)chart($('#outcome-chart'),data.accounting['1'].points.filter(p=>p.date>=data.entry_date&&p.date<=data.exit_date),['FMS','ICUI','basket'],{readout:$('#outcome-readout'),label:'Previously evaluated beneficiary net hedged movement'});
    },120);});
    renderCase();
  } catch(error) {
    $('#case-error').hidden=false;$('#case-error').textContent=error.message;
    $('#reveal-case').disabled=true;
    $('#case-chart').innerHTML='<div class="empty-state">The saved case could not be loaded. No substitute curve is displayed.</div>';
  }
}
