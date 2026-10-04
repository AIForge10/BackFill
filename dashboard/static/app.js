import { drawIntegrity } from './dial.js';
import { initCase } from './case.js';

const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const numeric = value => value === '' || value === null || value === undefined ? null : Number(value);
const fixed = (value, digits=2) => numeric(value) === null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(digits);
const pct = (value, digits=2) => numeric(value) === null ? '—' : `${fixed(Number(value)*100,digits)}%`;
const money = value => numeric(value) === null ? '—' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(Number(value));
const shortMoney = value => numeric(value) === null ? '—' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',notation:'compact',maximumFractionDigits:1}).format(Number(value));
const text = (selector, value) => { $(selector).textContent = value ?? '—'; };
const safeURL = value => { try { const url=new URL(value); return ['https:','http:'].includes(url.protocol) ? url.href : null; } catch { return null; } };
const link = (url,label) => safeURL(url) ? `<a class="text-link" href="${esc(safeURL(url))}" target="_blank" rel="noopener">${esc(label)} ↗</a>` : '<span class="small-note">Source URL not supplied</span>';
const empty = (title,description) => `<div class="empty-state"><span class="empty-icon" aria-hidden="true">·</span><strong>${esc(title)}</strong><p>${esc(description)}</p></div>`;
const params = new URLSearchParams(location.search);
const state = { strategy:['candidate','primary','basket'].includes(params.get('strategy'))?params.get('strategy'):'candidate',
  vendor:params.get('vendor')==='webull_only'?'webull_only':'reference_mix', costs:params.get('costs')==='2'?2:1,
  chart:'return', offset:0, limit:15, overview:null, research:null, request:0, evidenceRequest:0, lastReceipt:null };

async function api(path) {
  const response=await fetch(path,{cache:'no-store'});
  if (!response.ok) throw new Error('The requested saved record is unavailable.');
  return response.json();
}

function badge(selector,label,attention=false,live=false) {
  text(selector,label); $(selector).classList.toggle('attention',attention); $(selector).classList.toggle('live',live);
}

function showToast(message) {
  text('#toast',message); $('#toast').hidden=false;
  clearTimeout(showToast.timer); showToast.timer=setTimeout(()=>$('#toast').hidden=true,2500);
}

function renderOverview(data) {
  state.overview=data;
  const matching=data.frozen_checks.filter(r=>r.status==='match').length;
  text('#integrity-count',`${String(matching).padStart(2,'0')} / ${String(data.frozen_checks.length).padStart(2,'0')}`);
  text('#integrity-total','SHA-256 / FROZEN INPUTS');
  badge('#integrity-badge',matching===data.frozen_checks.length?'Frozen files match':'Source mismatch',matching!==data.frozen_checks.length);
  drawIntegrity($('#integrity-dial'),matching,data.frozen_checks.length);
  $('#strategy-comparison').innerHTML=data.strategies.map(item=>`<button class="comparison-cell" data-strategy="${esc(item.id)}" aria-pressed="${item.id===state.strategy}"><span><b>${esc(item.name)}</b><small>${esc(item.classification)}</small></span><strong>${fixed(item.metrics?.sharpe)}</strong></button>`).join('');
  $('#strategy-comparison').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{state.strategy=button.dataset.strategy;$('#strategy').value=state.strategy;loadResearch();}));
  text('#holdout-note',`${data.protected_period.start} → ${data.protected_period.end}: ${data.protected_period.explanation}`);
  $('#risk-limits').innerHTML=[['Per listed owner',data.limits.name],['Per listing market',data.limits.country],['Healthcare sector',data.limits.sector],['Gross exposure',data.limits.gross],['Absolute net exposure',data.limits.net]].map(([label,value])=>`<div class="risk-limit"><span>${label}</span><strong>${pct(value,0)}</strong></div>`).join('');
  $('#hash-records').innerHTML=data.frozen_checks.map(row=>`<div class="hash-row"><div><span>${esc(row.file)}</span><span>${row.status==='match'?'✓ MATCH':esc(row.status.toUpperCase())}</span></div><code>${esc(row.actual??'No local file')}</code></div>`).join('');
  $('#limitations').innerHTML=data.notices.map(notice=>`<li>${esc(notice)}</li>`).join('');
  $('#variant-rows').innerHTML=data.summary.map(row=>`<tr><td>${esc(row.rule)}</td><td>${esc(row.vendor_policy)}</td><td>×${esc(row.cost_multiplier)}</td><td>${fixed(row.sharpe)}</td><td>${esc(row.positions)}</td><td>${fixed(row.winner_p,3)}</td></tr>`).join('');
  const symbols=Object.entries(data.manifest.symbols??{}).filter(([name])=>!name.startsWith('^'));
  $('#price-provenance').innerHTML=symbols.map(([ticker,item])=>`<div class="vendor-row"><span>${esc(ticker)} <small>${esc(item.vendor??'Recorded vendor')}</small></span><small>${esc(item.actual_start??'—')} → ${esc(item.actual_end??'—')}</small></div>`).join('');
  text('#reproduce-command',data.reproduction);
}

async function loadResearch() {
  const request=++state.request;
  $('#research-error').hidden=true;
  badge('#research-status','Loading saved outputs');
  $('#cost-switch').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.cost)===state.costs)));
  $('#strategy-comparison').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.strategy===state.strategy)));
  history.replaceState(null,'',`?strategy=${state.strategy}&vendor=${state.vendor}&costs=${state.costs}`);
  try {
    const data=await api(`/api/research?strategy=${state.strategy}&vendor=${state.vendor}&costs=${state.costs}`);
    if(request!==state.request)return;
    state.research=data;
    renderResearch(data);
  } catch(error) {
    if(request!==state.request)return;
    $('#research-error').hidden=false;text('#research-error',error.message);
    renderResearch({id:state.strategy,available:false,reason:error.message});
  }
}

function renderResearch(data) {
  const m=data.metrics??{};
  text('#metric-sharpe',fixed(m.sharpe));text('#metric-return',pct(m.annualized_return));
  text('#metric-vol',pct(m.annualized_volatility));text('#metric-dd',pct(m.max_drawdown));
  text('#metric-sample',m.positions===undefined?'—':`${m.positions} / ${m.events}`);
  text('#sample-foot',data.id==='basket'?'Reported executed sample':'Distinct source events');
  badge('#research-status',data.available?data.classification:'Scenario unavailable',data.id==='basket'||!data.available);
  text('#winner-p',fixed(m.inference?.p_value,3));text('#paired-p',fixed(data.comparison?.p_value,3));
  text('#turnover',fixed(m.annualized_turnover)+'×');
  const interpretations={candidate:'Positive in this small selected sample, with wide uncertainty. AMRX drives most of the profit. The timing was selected after seeing in-sample results.',primary:'The historical supplier primary did not support the original 60-session effect. Keep this result visible alongside later exploration.',basket:'A reported positive specialist-basket result. Most basket members lack product-specific supplier evidence. Price exclusions redistribute capital; independent cache replay is pending.'};
  text('#result-interpretation',data.available?interpretations[data.id]:data.reason);
  $('#rules-content').innerHTML=`<div class="rules-list">${(data.rules??[]).map(rule=>`<span>${esc(rule)}</span>`).join('')}</div><p>Price source: ${esc(data.vendor??'Not supplied')} · Run: ${esc(data.run_id??'Historical reference')}</p><div class="source-hash">${esc(data.source??'No source supplied')}<br>SHA-256 ${esc(data.source_hash??'Unavailable')}${data.source_commit?`<br>Source commit ${esc(data.source_commit)}`:''}</div>`;
  $('#trade-rows').innerHTML=data.lots?.length?data.lots.map(row=>`<tr><td>${esc(row.ticker)}</td><td>${esc(row.trade_date)} → ${esc(row.exit_date)}</td><td>${fixed(row.beta,3)}</td><td>${money(row.entry_usd)}</td><td class="${Number(row.net_lot_return)<0?'negative':''}">${pct(row.net_lot_return)}</td><td>${money(row.net_pnl)}</td></tr>`).join(''):'<tr><td colspan="6">Executed-lot outputs are not supplied for this scenario.</td></tr>';
  const totalPnl=(data.concentration??[]).reduce((total,row)=>total+Number(row.net_pnl),0);
  const maximum=Math.max(1,...(data.concentration??[]).map(row=>Math.abs(Number(row.net_pnl))));
  $('#concentration').innerHTML=data.concentration?.length?data.concentration.map((row,index)=>`<div class="contribution-row"><div class="contribution-label"><span>${esc(row.ticker)} / ${esc(row.positions)} LOT${Number(row.positions)===1?'':'S'}</span><span>${money(row.net_pnl)}</span></div><div class="contribution-track"><div class="contribution-fill ${Number(row.net_pnl)<0?'negative':''}" id="contribution-${index}"></div></div></div>`).join(''):empty('Contribution unavailable','No company-level output is supplied for this scenario.');
  (data.concentration??[]).forEach((row,index)=>$(`#contribution-${index}`).style.width=`${Math.abs(Number(row.net_pnl))/maximum*100}%`);
  const amrx=(data.concentration??[]).find(row=>row.ticker==='AMRX');
  text('#concentration-note',amrx&&totalPnl>0?`AMRX contributes ${pct(Number(amrx.net_pnl)/totalPnl,0)} of net dollar profit. The full sample remains visible.`:'Company contributions must be available before attributing an edge.');
  const capacity=(data.capacity??[]).filter(row=>row.status==='ok'&&Number(row.capacity_usd_1pct)>0);
  const bound=capacity.length?Math.min(...capacity.map(row=>Number(row.capacity_usd_1pct))):null;
  text('#capacity-number',shortMoney(bound));
  text('#capacity-note',bound===null?'Capacity observations are not supplied for this scenario.':`Minimum order-based bound at 1% of prior 60-session ADV. ${capacity.length} recorded stock and hedge orders.`);
  const factors=m.factor_regression?.coefficients;
  $('#factor-exposures').innerHTML=factors?`<span class="eyebrow">FACTOR BETAS / MONTHLY USD PROXY</span>${['Mkt-RF','HML','Mom'].map(key=>`<div class="factor-item"><span>${esc(key)}</span><span>${fixed(factors[key],4)}</span></div>`).join('')}`:'<div class="small-note">Market / value / momentum exposure outputs not supplied.</div>';
  for(const [id,file]of [['equity-download','equity.csv'],['capacity-download','capacity.csv'],['lots-download','lots.csv'],['trades-download','trades.csv']]) {
    const element=$(`#${id}`);
    if(data.id==='candidate'&&data.available){element.href=`/api/download/${file}?costs=${state.costs}&vendor=${state.vendor}`;element.removeAttribute('aria-disabled');}
    else{element.removeAttribute('href');element.setAttribute('aria-disabled','true');}
  }
  renderChart();
}

function series(rows,mode) {
  let peak=Number(rows[0]?.nav)||1;
  const first=peak;
  return rows.map(row=>{const nav=Number(row.nav);peak=Math.max(peak,nav);return {date:row.date,value:mode==='drawdown'?(nav/peak-1)*100:(nav/first-1)*100};});
}

function renderChart() {
  const data=state.research;
  text('#chart-title',state.chart==='drawdown'?'Portfolio drawdown':'Net cumulative return');
  if(!data?.equity?.length) {
    $('#equity-chart').innerHTML=empty('Daily series not supplied',data?.reason??'Choose a scenario with saved daily equity outputs.');
    text('#chart-activity','No curve is reconstructed from summary metrics.');return;
  }
  const selected=series(data.equity,state.chart), control=series(data.control_equity??[],state.chart);
  const values=[...selected,...control].map(row=>row.value);
  const minimum=Math.min(0,...values),maximum=Math.max(0,...values);
  const padding=Math.max((maximum-minimum)*.15,.015),low=minimum-padding,high=maximum+padding;
  const width=780,height=245,left=49,right=15,top=18,bottom=32;
  const x=i=>left+i/Math.max(selected.length-1,1)*(width-left-right);
  const y=v=>top+(high-v)/(high-low)*(height-top-bottom);
  const points=data=>data.map((row,index)=>`${x(index).toFixed(2)},${y(row.value).toFixed(2)}`).join(' ');
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${state.chart==='drawdown'?'Drawdown':'Net cumulative return'} of saved strategy and same-date controls, June 2014 through September 2024"><title>Actual saved daily NAV, including modeled costs and idle cash</title>`;
  for(let i=0;i<5;i++){const value=low+(high-low)*i/4;const yy=y(value);svg+=`<line class="chart-grid" x1="${left}" y1="${yy}" x2="${width-right}" y2="${yy}"/><text class="chart-label" x="${left-8}" y="${yy+3}" text-anchor="end">${fixed(value,2)}%</text>`;}
  svg+=`<line class="chart-zero" x1="${left}" y1="${y(0)}" x2="${width-right}" y2="${y(0)}"/>`;
  for(let i=0;i<6;i++){const index=Math.round((selected.length-1)*i/5);svg+=`<text class="chart-label" x="${x(index)}" y="${height-6}" text-anchor="${i===0?'start':i===5?'end':'middle'}">${esc(selected[index].date.slice(0,7))}</text>`;}
  svg+=`<polyline class="chart-series control" points="${points(control)}"/><polyline class="chart-series" points="${points(selected)}"/>`;
  const last=selected.at(-1);svg+=`<rect class="chart-marker" x="${x(selected.length-1)-3}" y="${y(last.value)-3}" width="6" height="6"/><line id="chart-cursor" class="chart-zero" x1="${left}" x2="${left}" y1="${top}" y2="${height-bottom}" visibility="hidden"/></svg>`;
  $('#equity-chart').innerHTML=svg;
  const activity=`${data.metrics.active_days} ACTIVE / ${data.metrics.sessions} TOTAL SESSIONS · ${data.metrics.positions} LOTS`;
  text('#chart-activity',activity);
  const chart=$('#equity-chart svg');
  chart.addEventListener('pointermove',event=>{
    const rect=chart.getBoundingClientRect(),px=(event.clientX-rect.left)/rect.width*width;
    const index=Math.min(selected.length-1,Math.max(0,Math.round((px-left)/(width-left-right)*(selected.length-1))));
    const cursor=$('#chart-cursor');cursor.setAttribute('visibility','visible');cursor.setAttribute('x1',x(index));cursor.setAttribute('x2',x(index));
    text('#chart-activity',`${selected[index].date} · STRATEGY ${fixed(selected[index].value)}% · CONTROL ${fixed(control[index]?.value)}%`);
  });
  chart.addEventListener('pointerleave',()=>{$('#chart-cursor').setAttribute('visibility','hidden');text('#chart-activity',activity);});
}

async function loadEvidence() {
  const request=++state.evidenceRequest;
  const query=new URLSearchParams({q:$('#search').value,ticker:$('#ticker-filter').value,role:$('#role-filter').value,offset:state.offset,limit:state.limit});
  try{
    const data=await api(`/api/evidence?${query}`);if(request!==state.evidenceRequest)return;
    if($('#ticker-filter').options.length===1)data.tickers.forEach(ticker=>$('#ticker-filter').add(new Option(ticker,ticker)));
    $('#evidence-rows').innerHTML=data.rows.length?data.rows.map(row=>`<tr><td>${esc(row.public_date)}${row.date_uncertain==='True'?'<small>DATE UNCERTAIN</small>':''}</td><td><span class="drug-name">${esc(row.product)}</span><small>${esc(row.company||'FDA-page-absent control')}</small></td><td><span class="ticker">${esc(row.ticker)}</span><small>${esc(row.country)} / ${esc(row.benchmark)}</small></td><td><span class="role-label ${esc(row.role)}">${esc({winner:'AVAILABLE',disrupted:'DISRUPTED',placebo:'PAGE-ABSENT',nonwinner:'OTHER LISTED'}[row.role]??row.role)}</span><small>Captured ${esc(row.capture_date)}</small></td><td>${esc(row.trade_ready_date)}<small>EVIDENCE READY</small></td><td><button class="quiet-button inspect-event" data-id="${esc(row.event_id)}" data-ticker="${esc(row.ticker)}" aria-label="Inspect ${esc(row.ticker)} ${esc(row.product)}">Inspect ↗</button></td></tr>`).join(''):'<tr><td colspan="6">No matching evidence records. Try another search or filter.</td></tr>';
    text('#evidence-count',data.total?`${state.offset+1}–${Math.min(state.offset+state.limit,data.total)} OF ${data.total} RECORDS / FROZEN LEDGER`:'0 MATCHING RECORDS');
    $('#previous').disabled=state.offset===0;$('#next').disabled=state.offset+state.limit>=data.total;
    $('#evidence-rows').querySelectorAll('.inspect-event').forEach(button=>button.addEventListener('click',()=>openEvent(button.dataset.id,button.dataset.ticker)));
  }catch(error){if(request!==state.evidenceRequest)return;$('#evidence-rows').innerHTML=`<tr><td colspan="6">${esc(error.message)}</td></tr>`;}
}

async function openEvent(id,ticker) {
  $('#event-content').innerHTML='<p>Loading source evidence…</p>';$('#event-dialog').showModal();
  try{
    const data=await api(`/api/event?id=${encodeURIComponent(id)}&ticker=${encodeURIComponent(ticker)}`);
    const row=data.selected,execution=data.executions[0];
    $('#event-content').innerHTML=`<h2 id="event-title">${esc(row.product)}</h2><div class="event-meta">${esc(row.ticker)} · ${esc(row.company||'Page-absent control')} · EVENT ${esc(row.event_id)}</div>${link(row.archive_url,'Open archived FDA source')}<div class="event-timeline"><div><b>PUBLIC OBSERVATION</b><span>${esc(row.public_date)}</span></div><div><b>SUPPLIER CAPTURE</b><span>${esc(row.capture_date)}</span></div><div><b>ACTUAL ENTRY / V1</b><span>${esc(execution?.trade_date??'Not executed')}</span></div><div><b>ACTUAL EXIT / V1</b><span>${esc(execution?.exit_date??'Not executed')}</span></div></div><p class="small-note">Information known at ${esc(row.known_at)}. Event dates can be interval-censored by archive gaps. Actual executions here refer to the saved mixed-vendor v1 candidate.</p><h3>Presentation-level evidence</h3>${row.presentations.length?row.presentations.map(item=>`<div class="presentation">${esc(item.presentation)}<small>${esc(item.availability_raw??item.availability)} · ALLOCATION: ${item.on_allocation?'YES':'NO'}</small></div>`).join(''): '<p class="small-note">This control is absent from the selected FDA page. Product manufacture absence is not verified.</p>'}<h3>Other listed roles &amp; controls</h3><div class="table-scroll"><table><thead><tr><th>Owner</th><th>Role</th><th>Evidence</th></tr></thead><tbody>${data.suppliers.map(peer=>`<tr><td>${esc(peer.ticker)}</td><td>${esc(peer.role)}</td><td>${peer.presentations.length} PRESENTATIONS</td></tr>`).join('')}</tbody></table></div>${execution?`<h3>Recorded trade accounting</h3><div class="event-meta">Entry total-return mark ${fixed(execution.entry_stock_mark,4)} → exit ${fixed(execution.exit_stock_mark,4)}<br>Prior-window beta ${fixed(execution.beta,4)} · hedge ${esc(execution.hedge)}<br>Capital ${money(execution.entry_usd)} · net P&amp;L ${money(execution.net_pnl)}<br>Transaction costs ${money(execution.transaction_cost)} · carry ${money(execution.hedge_carry_cost)}<br>Net lot return ${pct(execution.net_lot_return)}</div>`:''}`;
  }catch(error){$('#event-content').textContent=error.message;}
}

async function loadLive() {
  $('#refresh-live').disabled=true;
  try{
    const data=await api('/api/live');
    badge('#live-badge',{not_configured:'Not connected',driver_missing:'Driver not installed',schema_missing:'Schema not ready',error:'Connection unavailable',empty:'Connected · awaiting data',connected:'Connected'}[data.state]??data.state,false,data.state==='connected');
    text('#live-checked',`Last checked: ${new Date(data.checked_at).toLocaleTimeString('en-US',{hour12:false})}`);
    text('#live-received',`Latest ingestion: ${data.latest_received_at?new Date(data.latest_received_at).toLocaleString():'No observations received'}`);
    $('#live-quotes').innerHTML=data.quotes.length?data.quotes.map(row=>{const change=row.previous_close?(Number(row.price)/Number(row.previous_close)-1):null;return `<div class="quote-row ${row.stale?'':'fresh-quote'}"><div><strong>${esc(row.ticker)}</strong><small>${esc(row.source)}</small></div><div><span class="quote-price">${fixed(row.price)}</span><small class="${change<0?'negative':''}">${pct(change)} VS PRIOR CLOSE</small></div><div><span class="badge ${row.stale?'':'live'}">${row.stale?'Stale':'Fresh'}</span><small>${esc(new Date(row.time).toLocaleString())}</small></div></div>`;}).join(''):empty(data.state==='empty'?'Awaiting market observations':'Live quotes unavailable',data.message);
    $('#live-events').innerHTML=data.events.length?data.events.map(row=>`<div class="live-event"><span class="role-label ${row.availability==='disrupted'?'disrupted':''}">${esc(row.availability.toUpperCase())} · ${esc(row.ticker??'UNMAPPED')}</span><p>${esc(row.product)}</p><span class="mono">${esc(row.company)} · ${esc(row.source)} · ${esc(new Date(row.observed_at).toLocaleString())}</span><div>${link(row.source_url,'Source notice')}</div></div>`).join(''):empty('Awaiting sourced supply updates',data.state==='not_configured'?'Configure Tiger Data and ingest supplier notices to observe them here.':data.message);
    if(state.lastReceipt&&data.latest_received_at&&state.lastReceipt!==data.latest_received_at){$('.live-layout').classList.remove('pulse-received');void $('.live-layout').offsetWidth;$('.live-layout').classList.add('pulse-received');}
    state.lastReceipt=data.latest_received_at;
  }catch(error){badge('#live-badge','Connection unavailable');$('#live-quotes').innerHTML=empty('Live monitor unavailable',error.message);}
  finally{$('#refresh-live').disabled=false;}
}

function scheduleLive() {
  clearTimeout(scheduleLive.timer);
  if($('#auto-refresh').checked&&!document.hidden)scheduleLive.timer=setTimeout(async()=>{await loadLive();scheduleLive();},15000);
}

$('#strategy').value=state.strategy;$('#vendor').value=state.vendor;
$('#strategy').addEventListener('change',event=>{state.strategy=event.target.value;loadResearch();});
$('#vendor').addEventListener('change',event=>{state.vendor=event.target.value;loadResearch();});
$('#cost-switch').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{state.costs=Number(button.dataset.cost);loadResearch();}));
$('.chart-switch').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{state.chart=button.dataset.chart;$('.chart-switch').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));renderChart();}));
let searchTimer;
$('#search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{state.offset=0;loadEvidence();},250);});
for(const selector of ['#ticker-filter','#role-filter'])$(selector).addEventListener('change',()=>{state.offset=0;loadEvidence();});
$('#previous').addEventListener('click',()=>{state.offset=Math.max(0,state.offset-state.limit);loadEvidence();});
$('#next').addEventListener('click',()=>{state.offset+=state.limit;loadEvidence();});
$('#close-dialog').addEventListener('click',()=>$('#event-dialog').close());
$('#event-dialog').addEventListener('click',event=>{if(event.target===$('#event-dialog')){const rect=event.target.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)event.target.close();}});
$('#refresh-live').addEventListener('click',async()=>{await loadLive();scheduleLive();});
$('#auto-refresh').addEventListener('change',scheduleLive);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&$('#auto-refresh').checked)loadLive();scheduleLive();});
$('#copy-command').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#reproduce-command').textContent);showToast('Reproduction command copied');}catch{showToast('Clipboard unavailable. Select and copy the command.');}});
if(!matchMedia('(prefers-reduced-motion: reduce)').matches){
  document.documentElement.classList.add('js-motion');
  const observer=new IntersectionObserver(entries=>entries.forEach(entry=>entry.target.classList.toggle('visible',entry.isIntersecting)),{threshold:.08});
  document.querySelectorAll('.reveal').forEach((element,index)=>{element.style.transitionDelay=`${Math.min(index%2,1)*110}ms`;observer.observe(element);});
}
try{renderOverview(await api('/api/overview'));}catch(error){badge('#integrity-badge','Research unavailable',true);text('#integrity-total','No integrity claim');showToast(error.message);}
await Promise.allSettled([loadResearch(),loadEvidence(),loadLive(),initCase()]);scheduleLive();
