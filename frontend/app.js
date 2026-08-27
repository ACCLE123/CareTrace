const API_BASE_URL = (window.CARETRACE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const state = { user: null, patient: null, timeline: [] };
const $ = (s) => document.querySelector(s);
const api = async (url, options = {}) => {
  const headers = { 'x-demo-user': state.user.id, ...(options.headers || {}) };
  if (options.body) headers['content-type'] = 'application/json';
  const res = await fetch(`${API_BASE_URL}${url}`, { ...options, headers });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Request failed');
  return res.status === 204 ? null : res.json();
};
const toast = (message) => { const node = $('#toast'); node.textContent = message; node.classList.add('show'); setTimeout(() => node.classList.remove('show'), 3200); };
const date = (value) => new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
function canAdd() { return ['staff', 'clinician'].includes(state.user.role); }
function renderHighlights(data) {
  $('#policy').textContent = data.policy;
  $('#highlights').innerHTML = data.highlights.map(h => `<article class="highlight ${h.importance >= 90 ? 'critical' : ''}"><span class="badge">${h.importance >= 90 ? 'critical safety floor' : 'attention suggested'} · ${h.importance}/100</span><p>${escape(h.excerpt)}</p><p class="reason">${escape(h.risk_reason)}</p><button class="source-link" data-source="${h.entry_id}">View source in timeline ↓</button></article>`).join('') || '<p class="subtle">No patient-visible highlights for this role.</p>';
  $('#actions').innerHTML = data.open_actions.map(x => `<div class="action">${escape(x.content)}</div>`).join('') || '<p class="subtle">No open actions.</p>';
  document.querySelectorAll('[data-source]').forEach(b => b.onclick = () => document.getElementById(`entry-${b.dataset.source}`)?.scrollIntoView({behavior:'smooth',block:'center'}));
}
function escape(v) { const e = document.createElement('div'); e.textContent = v || ''; return e.innerHTML; }
function renderTimeline(entries) {
  state.timeline = entries;
  $('#timeline-list').innerHTML = entries.map(e => `<article id="entry-${e.id}" class="entry ${e.author_role}"><div class="entry-card"><div class="entry-meta"><span>${escape(e.author_name)} · ${escape(e.entry_type.replaceAll('_',' '))}</span><span>${date(e.created_at)}</span></div><p class="entry-content">${escape(e.content)}</p><div class="entry-footer"><span class="internal">${e.visibility === 'patient' ? 'PATIENT-FACING' : 'INTERNAL'}</span>${e.provenance_pointer ? `<span class="internal">SOURCE: ${escape(e.provenance_pointer)}</span>` : ''}${['staff','clinician'].includes(state.user.role) ? `<button data-versions="${e.id}">History · v${e.version}</button><button data-comment="${e.id}">Comment</button>` : ''}</div></div></article>`).join('');
  document.querySelectorAll('[data-versions]').forEach(b => b.onclick = () => showVersions(b.dataset.versions));
  document.querySelectorAll('[data-comment]').forEach(b => b.onclick = () => comment(b.dataset.comment));
}
async function showVersions(id) {
  try { const versions = await api(`/api/entries/${id}/versions`); const entry = state.timeline.find(x => x.id === id); $('#version-list').innerHTML = versions.map(v => `<div class="version"><b>Version ${v.version}</b> · ${date(v.created_at)}<br/>${escape(v.content)}${v.version !== entry.version ? `<br/><button data-revert="${v.version}">Revert to this version</button>` : ''}</div>`).join(''); $('#versions').showModal(); document.querySelectorAll('[data-revert]').forEach(b => b.onclick = async () => { try { await api(`/api/entries/${id}/revert`, { method:'POST', body:JSON.stringify({target_version:+b.dataset.revert, expected_version:entry.version}) }); $('#versions').close(); toast('Reverted — a new version and audit event were created.'); await refresh(); } catch(err) { toast(err.message); } }); } catch(err) { toast(err.message); }
}
async function comment(id) { const body = prompt('Internal comment (visible only to staff / clinicians):'); if (!body) return; try { await api(`/api/entries/${id}/comments`, { method:'POST', body:JSON.stringify({body, mention_role:'clinician'}) }); toast('Comment added to the internal audit trail.'); } catch(err) { toast(err.message); } }
async function refresh() { const [glance, timeline] = await Promise.all([api(`/api/patients/${state.patient.id}/glance`), api(`/api/patients/${state.patient.id}/timeline`)]); renderHighlights(glance); renderTimeline(timeline); }
async function boot() {
  const identities = await fetch(`${API_BASE_URL}/api/demo-identities`).then(r => r.json());
  $('#identity').innerHTML = identities.map(i => `<option value="${i.id}">${i.display_name} — ${i.role}</option>`).join('');
  state.user = identities.find(i => i.role === 'clinician');
  $('#identity').value = state.user.id;
  const patients = await api('/api/patients'); state.patient = patients[0]; $('#patient-name').textContent = state.patient.display_name;
  await refresh(); $('#new-note').style.display = canAdd() ? '' : 'none';
}
$('#identity').onchange = async (e) => { const identities = await fetch(`${API_BASE_URL}/api/demo-identities`).then(r => r.json()); state.user = identities.find(i => i.id === e.target.value); $('#new-note').style.display = canAdd() ? '' : 'none'; $('#note-form').classList.add('hidden'); try { await refresh(); toast(`Viewing as ${state.user.role}. Server permissions applied.`); } catch(err) { toast(err.message); } };
$('#new-note').onclick = () => $('#note-form').classList.remove('hidden');
$('#cancel-note').onclick = () => $('#note-form').classList.add('hidden');
$('#note-form').onsubmit = async (e) => { e.preventDefault(); const f = new FormData(e.currentTarget); try { await api(`/api/patients/${state.patient.id}/entries`, {method:'POST',body:JSON.stringify(Object.fromEntries(f))}); e.currentTarget.reset(); e.currentTarget.classList.add('hidden'); toast('Saved with version 1 and an audit record.'); await refresh(); } catch(err) { toast(err.message); } };
$('#close-dialog').onclick = () => $('#versions').close();
boot().catch(err => toast(err.message));
