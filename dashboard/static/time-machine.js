// FDA Time Machine: point-in-time FDA shortage pages from Tiger Data. Read-only; one request per date.
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL = value => { try { const url = new URL(value); return url.protocol === 'https:' ? url.href : null; } catch { return null; } };
const utcDay = iso => String(iso ?? '').slice(0, 10);
const utcStamp = iso => iso ? `${String(iso).slice(0, 10)} ${String(iso).slice(11, 16)} UTC` : '—';
const daysBetween = (fromIso, toDay) => Math.round((Date.parse(`${toDay}T23:59:59Z`) - Date.parse(fromIso)) / 864e5);
const OLD_PAGE_DAYS = 90, PAGE_SIZE = 100;
const params = new URLSearchParams(location.search);
const state = { data: null, status: 'Currently in Shortage', query: '', shown: PAGE_SIZE, request: 0 };

async function api(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error('That request could not be answered. Check the date format.');
  return response.json();
}

function setBadge(label, attention = false, live = false) {
  $('#tm-state').textContent = label;
  $('#tm-state').classList.toggle('attention', attention);
  $('#tm-state').classList.toggle('live', live);
}

function visibleDrugs() {
  const q = state.query.toLowerCase();
  return (state.data?.drugs ?? []).filter(d => (!state.status || d.status === state.status)
    && (!q || d.drug.toLowerCase().includes(q) || d.manufacturers.some(m => m.toLowerCase().includes(q))));
}

function renderTable() {
  const data = state.data, day = data?.date;
  if (!data || data.state !== 'connected') {
    $('#tm-rows').innerHTML = `<tr><td colspan="5">${esc(data?.message ?? 'Loading…')}</td></tr>`;
    $('#tm-shown').textContent = ''; $('#tm-more').hidden = true; return;
  }
  const rows = visibleDrugs();
  if (!rows.length) {
    const why = data.before_first_snapshot ? `No FDA page had been archived yet on ${day}. The archive starts ${utcDay(data.range?.first)}.` : 'No drugs match this filter.';
    $('#tm-rows').innerHTML = `<tr><td colspan="5">${esc(why)}</td></tr>`;
  } else {
    $('#tm-rows').innerHTML = rows.slice(0, state.shown).map(d => {
      const age = daysBetween(d.snapshot_ts, day), old = age > OLD_PAGE_DAYS, link = safeURL(d.source_url);
      const status = d.status === 'Currently in Shortage' ? 'is-shortage' : d.status === 'Resolved' ? 'is-resolved' : '';
      return `<tr><td><button type="button" class="tm-drug" data-drug="${esc(d.drug)}">${esc(d.drug)}</button></td>`
        + `<td><span class="tm-status ${status}">${esc(d.status)}</span></td>`
        + `<td class="tm-mfrs">${d.manufacturers.map(esc).join('<br>')}</td>`
        + `<td class="mono">${esc(utcStamp(d.snapshot_ts))}<small class="${old ? 'tm-old' : ''}">${age === 0 ? 'same day' : `${age} day${age === 1 ? '' : 's'} before`}${old ? ' · older page' : ''}</small></td>`
        + `<td>${link ? `<a class="text-link" href="${esc(link)}" target="_blank" rel="noopener">Archived page ↗</a>` : '<span class="small">No archive link</span>'}</td></tr>`;
    }).join('');
  }
  $('#tm-shown').textContent = `${Math.min(rows.length, state.shown)} of ${rows.length} drugs shown`;
  $('#tm-more').hidden = rows.length <= state.shown;
  document.querySelectorAll('.tm-drug').forEach(b => b.addEventListener('click', () => loadTimeline(b.dataset.drug)));
}

function renderSnapshot() {
  const data = state.data;
  $('#tm-asof-date').textContent = data?.date ?? '—';
  if (!data || data.state !== 'connected') {
    $('#tm-newest').textContent = '—'; $('#tm-counts').innerHTML = '';
    $('#tm-message').textContent = data?.message ?? '';
    setBadge({not_configured: 'Not connected', driver_missing: 'Driver missing', schema_missing: 'Not loaded', error: 'Tiger unreachable'}[data?.state] ?? 'Unavailable', true);
    return;
  }
  setBadge('Tiger Data · read-only', false, true);
  $('#tm-newest').textContent = utcStamp(data.latest_snapshot_ts);
  $('#tm-counts').innerHTML = Object.entries(data.counts).sort((a, b) => b[1] - a[1])
    .map(([status, n]) => `<span><strong>${n}</strong> ${esc(status)}</span>`).join('');
  const old = data.drugs.filter(d => daysBetween(d.snapshot_ts, data.date) > OLD_PAGE_DAYS).length;
  $('#tm-message').textContent = `${data.message}${old ? ` ${old} of them were last archived more than ${OLD_PAGE_DAYS} days before this date (marked "older page").` : ''}`;
  if (data.range) {
    $('#tm-date').min = utcDay(data.range.first); $('#tm-date').max = new Date().toISOString().slice(0, 10);
    $('#tm-range').textContent = `Archive covers ${utcDay(data.range.first)} → ${utcDay(data.range.last)} · ${data.range.drugs} drugs`;
  }
}

async function loadDate(day) {
  const request = ++state.request;
  state.shown = PAGE_SIZE;
  setBadge('Loading');
  history.replaceState(null, '', `?date=${day}`);
  try {
    const data = await api(`/api/fda/asof?date=${encodeURIComponent(day)}`);
    if (request !== state.request) return;
    state.data = data;
  } catch (error) {
    if (request !== state.request) return;
    state.data = { date: day, state: 'error', message: error.message };
  }
  renderSnapshot(); renderTable();
}

async function loadTimeline(drug) {
  $('#tm-timeline').hidden = false;
  $('#tm-timeline-title').textContent = drug;
  $('#tm-timeline-summary').textContent = 'Loading timeline…';
  $('#tm-changes').innerHTML = '';
  $('#tm-timeline').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest' });
  try {
    const t = await api(`/api/fda/timeline?drug=${encodeURIComponent(drug)}`);
    if (t.state !== 'connected' || !t.changes.length) { $('#tm-timeline-summary').textContent = t.message ?? 'No timeline available.'; return; }
    const changed = t.changes.length - 1;
    $('#tm-timeline-summary').textContent = `${t.snapshots} archived snapshots from ${utcDay(t.first)} to ${utcDay(t.last)} · ${changed ? `${changed} status change${changed === 1 ? '' : 's'}` : 'status never changed'}`;
    $('#tm-changes').innerHTML = t.changes.map(c => {
      const link = safeURL(c.source_url);
      return `<li><span class="mono">${esc(utcStamp(c.snapshot_ts))}</span><span class="tm-status ${c.status === 'Currently in Shortage' ? 'is-shortage' : c.status === 'Resolved' ? 'is-resolved' : ''}">${esc(c.status)}</span>`
        + `<span class="small">${c.from_status ? `from ${esc(c.from_status)}` : 'first archived'} · ${c.manufacturers} manufacturer${c.manufacturers === 1 ? '' : 's'}</span>`
        + `${link ? `<a class="text-link" href="${esc(link)}" target="_blank" rel="noopener">Page ↗</a>` : ''}</li>`;
    }).join('');
  } catch (error) { $('#tm-timeline-summary').textContent = error.message; }
}

const today = new Date().toISOString().slice(0, 10);
const initial = /^\d{4}-\d{2}-\d{2}$/.test(params.get('date') ?? '') ? params.get('date') : today;
$('#tm-date').value = initial;
$('#tm-date').addEventListener('change', () => { if ($('#tm-date').value) loadDate($('#tm-date').value); });
$('#tm-status').querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
  state.status = b.dataset.status; state.shown = PAGE_SIZE;
  $('#tm-status').querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  $('#tm-table-title').textContent = state.status ? 'Shortages and manufacturers' : 'All archived drug pages and manufacturers';
  renderTable();
}));
let searchTimer;
$('#tm-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.query = $('#tm-search').value.trim(); state.shown = PAGE_SIZE; renderTable(); }, 200); });
$('#tm-more').addEventListener('click', () => { state.shown += PAGE_SIZE; renderTable(); });
$('#tm-timeline-close').addEventListener('click', () => { $('#tm-timeline').hidden = true; });
loadDate(initial);
