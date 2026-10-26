'use strict';
/* ApplyBot UI - core: helpers, API, router, task polling, prompts, modals. */

const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  jobs: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  rocket: '<path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2.1-.1-2.9a2.2 2.2 0 0 0-2.9-.1z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.9A12.9 12.9 0 0 1 22 2c0 2.7-.8 7.5-6 11a22.4 22.4 0 0 1-4 2z"/><path d="M9 12H4s.6-3 2-4c1.6-1.1 5 0 5 0M12 15v5s3-.6 4-2c1.1-1.6 0-5 0-5"/>',
  send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
  sparkles: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  file: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
  save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  play: '<path d="m7 4 13 8-13 8z"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
  cpu: '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z"/>',
  key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',
  mapPin: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
  zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>',
  hand: '<path d="M18 11V6a2 2 0 0 0-4 0M14 10V4a2 2 0 0 0-4 0v2M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.9-6-2.4l-3.6-3.6a2 2 0 0 1 2.8-2.8L7 15"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
};
const icon = (n, cls = '') => `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n] || ''}</svg>`;

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const plural = (n, w, p) => `${n} ${n === 1 ? w : (p || w + 's')}`;
const humanize = (k) => String(k).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

async function api(path, body) {
  const opts = { headers: { 'X-ApplyBot': '1' } };
  if (body !== undefined) {
    opts.method = 'POST';
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  let data = {};
  try { data = await r.json(); } catch (_) { /* empty */ }
  if (!r.ok) {
    const err = new Error(data.error || `Request failed (${r.status})`);
    err.status = r.status;
    throw err;
  }
  return data;
}

/* ------------------------------------------------------------- formatting */
const STATUS_LABEL = {
  new: 'New', matched: 'Matched', rejected: 'Rejected', tailored: 'Tailored', applied: 'Applied',
  needs_review: 'Needs review', failed: 'Failed', skipped: 'Skipped', dry_run: 'Dry run',
  interviewing: 'Interviewing', offer: 'Offer', rejected_by_company: 'Rejected by company',
  running: 'Running', done: 'Done', cancelled: 'Stopped', submitted: 'Applied',
};
const pill = (s) => `<span class="pill st-${esc(s)}">${esc(STATUS_LABEL[s] || humanize(s || 'unknown'))}</span>`;
function scoreBadge(score) {
  if (score === null || score === undefined || score === '') return '<span class="score na" title="Not scored yet">–</span>';
  const n = Math.round(Number(score));
  const cls = n >= 75 ? 'hi' : n >= 55 ? 'mid' : 'lo';
  return `<span class="score ${cls}" title="Match score">${n}</span>`;
}
function avatar(name, lg = false) {
  const s = String(name || '?').trim();
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 360;
  const letters = s.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?';
  return `<span class="avatar${lg ? ' lg' : ''}" style="background:hsl(${h} 62% 52%)">${esc(letters)}</span>`;
}
function parseDate(v) {
  if (!v) return null;
  if (typeof v === 'number') return new Date(v < 1e12 ? v * 1000 : v);
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(v) ? v + 'T12:00:00' : v);
  return isNaN(d) ? null : d;
}
function timeAgo(v) {
  const d = parseDate(v);
  if (!d) return '';
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.round(s / 86400)}d ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}
const fmtDate = (v) => { const d = parseDate(v); return d ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : ''; };
function duration(sec) {
  sec = Math.max(0, Math.round(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
}
const fmtSize = (b) => b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;

/* ----------------------------------------------------------------- toasts */
function toast(msg, kind = 'info', ms = 4200) {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.innerHTML = `${icon(kind === 'ok' ? 'checkCircle' : kind === 'err' ? 'alert' : 'info')}<span>${esc(msg)}</span>`;
  $('#toasts').appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateY(6px)'; setTimeout(() => el.remove(), 250); }, ms);
}
const fail = (e) => toast(e.message || String(e), 'err', 7000);

/* ------------------------------------------------------------------ state */
const S = {
  state: null, page: null, dirty: false, lastHash: '',
  jobs: { f: { status: 'matched', q: '', source: '', min_score: '', sort: 'score' }, list: [], total: 0, tabs: {}, sel: new Set() },
  task: null, taskId: null, log: [], logCount: 0, pollT: null, promptShown: null,
  drawerId: null, tags: {},
};

/* ----------------------------------------------------------------- router */
const PAGES = {};  // filled by pages.js / settings.js: name -> {title, icon, section, render}
const NAV = [
  ['Workflow', ['dashboard', 'jobs', 'apply', 'activity']],
  ['You', ['profile', 'answers', 'settings']],
];

function go(page) { location.hash = '#/' + page; }

function route() {
  const name = (location.hash.replace(/^#\/?/, '').split('?')[0]) || 'dashboard';
  if (S.dirty && location.hash !== S.lastHash) {
    if (!confirm('You have unsaved changes. Leave this page and discard them?')) {
      history.replaceState(null, '', S.lastHash || '#/dashboard');
      return;
    }
  }
  S.dirty = false;
  S.lastHash = location.hash || '#/dashboard';
  S.page = PAGES[name] ? name : 'dashboard';
  closeDrawer();
  renderNav();
  const main = $('#main');
  main.scrollTop = 0;
  main.innerHTML = '<div class="page"><div class="skeleton" style="height:120px"></div></div>';
  Promise.resolve(PAGES[S.page].render(main)).catch((e) => {
    main.innerHTML = `<div class="page"><div class="callout err">${icon('alert')}<div><b>Couldn't load this page.</b><br>${esc(e.message)}</div></div></div>`;
  });
}

function renderNav() {
  const c = (S.state && S.state.counts) || {};
  const counts = { jobs: c.matched || 0, activity: c.needs_review || 0 };
  $('#nav').innerHTML = NAV.map(([label, pages]) => `
    <div class="nav-label">${label}</div>
    ${pages.filter((p) => PAGES[p]).map((p) => `
      <a href="#/${p}" class="${S.page === p ? 'active' : ''}">${icon(PAGES[p].icon)}<span>${PAGES[p].title}</span>
        ${counts[p] ? `<span class="count" title="${p === 'jobs' ? 'Matched jobs' : 'Need review'}">${counts[p]}</span>` : ''}</a>`).join('')}
  `).join('');
  if (S.state) $('#version').textContent = 'v' + S.state.version;
}

async function loadState() {
  S.state = await api('/api/state');
  renderNav();
  return S.state;
}

function setDirty(v = true) { S.dirty = v; }
window.addEventListener('beforeunload', (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ''; } });

/* ------------------------------------------------------------ task polling */
const BUSY_PAGES_NAV = new Set(['search', 'score', 'run', 'apply', 'apply_url', 'install_browser']);

async function startTask(kind, body = {}, opts = {}) {
  try {
    await api('/api/tasks/' + kind, body);
  } catch (e) {
    if (e.status === 409) toast('Another task is already running. Stop it or wait for it to finish.', 'err');
    else fail(e);
    return false;
  }
  S.logCount = 0;
  S.taskId = null;
  if (opts.toast !== false) toast(opts.msg || 'Started', 'info', 2500);
  if (opts.navigate !== false && BUSY_PAGES_NAV.has(kind) && S.page !== 'activity') go('activity');
  pollSoon(150);
  return true;
}

function pollSoon(ms = 0) { clearTimeout(S.pollT); S.pollT = setTimeout(poll, ms); }

async function poll() {
  clearTimeout(S.pollT);
  let ok = true;
  try {
    const d = await api(`/api/task?since=${S.logCount}&id=${encodeURIComponent(S.taskId || '')}`);
    handleTask(d);
  } catch (_) { ok = false; }
  document.body.classList.toggle('offline', !ok);
  const busy = S.task && S.task.status === 'running';
  S.pollT = setTimeout(poll, !ok ? 4000 : busy ? 800 : 3000);
}

function handleTask(d) {
  const t = d.task;
  const prev = S.task;
  if (!t) {
    S.task = null; S.taskId = null; S.log = []; S.logCount = 0;
    renderTaskPill();
    setTitle(false);
    return;
  }
  let fresh = false;
  if (t.id !== S.taskId) { S.taskId = t.id; S.log = d.lines.slice(); fresh = true; }
  else if (d.lines.length) S.log.push(...d.lines);
  if (S.log.length > 5000) S.log.splice(0, S.log.length - 5000);
  S.logCount = d.count;
  S.task = t;
  if (S.page === 'activity') {
    if (fresh) renderConsole(); else if (d.lines.length) appendConsole(d.lines);
    renderTaskHead();
  }
  renderTaskPill();

  if (t.prompt && S.promptShown !== t.prompt.id) showPrompt(t.prompt);
  if (!t.prompt && S.promptShown) closePrompt();
  setTitle(!!t.prompt);

  if (prev && prev.id === t.id && prev.status === 'running' && t.status !== 'running') onTaskFinished(t);
}

function setTitle(attention) {
  const want = attention ? '(!) ApplyBot - action needed' : 'ApplyBot';
  if (document.title !== want) document.title = want;
}

async function onTaskFinished(t) {
  const name = t.name || 'Task';
  if (t.status === 'done') toast(`${name} finished`, 'ok');
  else if (t.status === 'cancelled') toast(`${name} stopped`, 'info');
  else toast(`${name} failed${t.error ? ': ' + t.error : ''}`, 'err', 9000);
  try { await loadState(); } catch (_) { /* ignore */ }
  if (['dashboard', 'jobs', 'activity'].includes(S.page)) PAGES[S.page].refresh?.();
  if (S.drawerId) openJob(S.drawerId, true);
}

function renderTaskPill() {
  const el = $('#taskpill');
  const t = S.task;
  if (!t || (t.status !== 'running' && Date.now() / 1000 - (t.ended || 0) > 60)) { el.innerHTML = ''; return; }
  const running = t.status === 'running';
  const sub = t.prompt ? 'Needs your input' : running ? (t.stopping ? 'Stopping…' : duration(Date.now() / 1000 - t.started)) : STATUS_LABEL[t.status] || t.status;
  el.innerHTML = `<a href="#/activity" class="taskpill${t.prompt ? ' attention' : ''}">
      ${running ? (t.prompt ? icon('hand') : '<span class="spin"></span>') : icon(t.status === 'done' ? 'checkCircle' : 'alert')}
      <span><span class="t-name">${esc(t.name)}</span><span class="t-sub">${esc(sub)}</span></span></a>`;
}

/* -------------------------------------------------------------- console */
function renderConsole() {
  const el = $('#console');
  if (!el) return;
  el.innerHTML = S.log.length ? S.log.map((l) => `<span class="ln">${l.html || '&nbsp;'}</span>`).join('')
    : '<span class="ln faint">Output from searches, scoring and applications appears here.</span>';
  el.scrollTop = el.scrollHeight;
}
function appendConsole(lines) {
  const el = $('#console');
  if (!el) return;
  if (el.querySelector('.faint') && el.children.length === 1) el.innerHTML = '';
  const stick = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  el.insertAdjacentHTML('beforeend', lines.map((l) => `<span class="ln">${l.html || '&nbsp;'}</span>`).join(''));
  while (el.children.length > 5000) el.firstChild.remove();
  if (stick) el.scrollTop = el.scrollHeight;
}
function renderTaskHead() {
  const el = $('#task-head');
  if (!el) return;
  const t = S.task;
  if (!t) {
    el.dataset.sig = '';
    el.innerHTML = `<div class="row">${icon('clock')}<div><b>Nothing running</b><div class="small muted">Start a search, scoring run or autopilot from the dashboard.</div></div></div>`;
    return;
  }
  const running = t.status === 'running';
  const secs = (t.ended || Date.now() / 1000) - t.started;
  const sig = [t.id, t.status, t.stopping, !!t.prompt, t.error].join('|');
  if (el.dataset.sig === sig) return;
  el.dataset.sig = sig;
  el.innerHTML = `
    <div class="row">
      ${running ? '<span class="spin"></span>' : icon(t.status === 'done' ? 'checkCircle' : 'alert', 'lg')}
      <div><b>${esc(t.name)}</b> ${pill(running ? 'running' : t.status)}
        <div class="small muted">${running ? 'Running for ' : 'Took '}<span id="task-elapsed">${duration(secs)}</span>${t.error ? ' · ' + esc(t.error) : ''}</div></div>
      <div class="spacer"></div>
      ${t.prompt ? `<button class="btn primary sm" data-act="reprompt">${icon('hand')} Answer question</button>` : ''}
      ${running ? `<button class="btn danger sm" data-act="stop-task" ${t.stopping ? 'disabled' : ''}>${icon('stop')} ${t.stopping ? 'Stopping…' : 'Stop'}</button>` : ''}
    </div>`;
}

/* ----------------------------------------------------------------- modals */
function openModal({ title, body, foot = '', wide = false, iconName = null, onClose = null, dismissable = true }) {
  const root = $('#modal');
  root.innerHTML = `<div class="modal-wrap" ${dismissable ? 'data-act="modal-bg"' : ''}>
    <div class="modal${wide ? ' wide' : ''}" role="dialog" aria-modal="true">
      <div class="modal-head">${iconName ? `<span class="modal-icon">${icon(iconName)}</span>` : ''}<h3>${esc(title)}</h3>
        <div class="spacer"></div>${dismissable ? `<button class="icon-btn" data-act="modal-close" title="Close">${icon('x')}</button>` : ''}</div>
      <div class="modal-body">${body}</div>
      ${foot ? `<div class="modal-foot">${foot}</div>` : ''}
    </div></div>`;
  root._onClose = onClose;
  const f = root.querySelector('[autofocus], .modal-body input:not([type=checkbox]):not([type=radio]), .modal-body textarea');
  if (f) setTimeout(() => f.focus(), 30);
  return root.querySelector('.modal');
}
function closeModal() {
  const root = $('#modal');
  const cb = root._onClose;
  root._onClose = null;
  root.innerHTML = '';
  if (cb) cb();
}

const MODES = [
  { id: 'dry_run', icon: 'eye', t: 'Dry run', d: 'Fill out forms but never submit. A screenshot is saved so you can check the result.' },
  { id: 'review', icon: 'hand', t: 'Review each', d: 'Fill everything in, then you approve every submission. Recommended.' },
  { id: 'auto', icon: 'zap', t: 'Autopilot', d: 'Submit automatically. Anything uncertain (CAPTCHA, login, unknown question) is flagged for you.' },
];
function modeCards(selected, name = 'mode') {
  return `<div class="mode-cards" data-mode-group="${name}">${MODES.map((m) => `
    <button type="button" class="mode-card${m.id === selected ? ' on' : ''}" data-act="pick-mode" data-mode="${m.id}">
      ${icon(m.icon)}<span class="mt">${m.t}</span><span class="md">${m.d}</span></button>`).join('')}</div>`;
}
const pickedMode = (root, name = 'mode') => $(`[data-mode-group="${name}"] .mode-card.on`, root)?.dataset.mode;
function switchHtml(id, on, label, hint = '') {
  return `<label class="switch"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><span class="track"></span>
    <span><span>${label}</span>${hint ? `<span class="tiny muted" style="display:block">${hint}</span>` : ''}</span></label>`;
}

function openApplyModal(ids, label) {
  const a = (S.state && S.state.apply) || {};
  openModal({
    title: label || `Apply to ${plural(ids.length, 'job')}`, iconName: 'send', wide: true,
    body: `<p class="muted" style="margin-top:0">ApplyBot opens each application, tailors your résumé and cover letter, and fills in the form.</p>
      ${modeCards(a.mode || 'review')}
      <div style="margin-top:16px">${switchHtml('m-headless', a.headless, 'Hide the browser window', 'Not used in Review mode — you need to see the form to approve it.')}</div>`,
    foot: `<button class="btn ghost" data-act="modal-close">Cancel</button>
      <button class="btn primary" id="m-go">${icon('send')} Start applying</button>`,
  });
  $('#m-go').onclick = () => {
    const mode = pickedMode($('#modal'));
    closeModal();
    startTask('apply', { ids, mode, headless: $('#m-headless')?.checked ?? false }, { msg: 'Applying…' });
  };
}

function openRunModal() {
  const st = S.state || {};
  const a = st.apply || {};
  openModal({
    title: 'Run autopilot', iconName: 'rocket', wide: true,
    body: `<p class="muted" style="margin-top:0">One click does everything: <b>find</b> new postings → <b>score</b> them against your profile →
        <b>tailor</b> a résumé for each strong match → <b>apply</b>.</p>
      ${modeCards(a.mode || 'review')}
      <div class="form-grid" style="margin-top:16px">
        <label>Maximum applications this run<input class="input" type="number" id="r-max" min="1" max="200" value="${a.max_per_run || 10}"></label>
        <label>Score at most this many new jobs<input class="input" type="number" id="r-score" min="1" max="2000" value="150"></label>
        <div>${switchHtml('r-skip', false, 'Skip searching', 'Only use jobs already found.')}</div>
        <div>${switchHtml('r-headless', a.headless, 'Hide the browser window', 'Ignored in Review mode.')}</div>
      </div>
      ${st.applied_today ? `<div class="callout info" style="margin-top:14px">${icon('info')}<div>You've applied to ${plural(st.applied_today, 'job')} today (daily cap ${a.max_per_day}).</div></div>` : ''}`,
    foot: `<button class="btn ghost" data-act="modal-close">Cancel</button>
      <button class="btn primary" id="r-go">${icon('rocket')} Start</button>`,
  });
  $('#r-go').onclick = () => {
    const body = {
      mode: pickedMode($('#modal')), max: Number($('#r-max').value) || 10, skip_search: $('#r-skip').checked,
      headless: $('#r-headless').checked, score_limit: Number($('#r-score').value) || 150,
    };
    closeModal();
    startTask('run', body, { msg: 'Autopilot started' });
  };
}

/* ---------------------------------------------------------------- prompts */
function showPrompt(p) {
  S.promptShown = p.id;
  let root = $('#prompt-root');
  if (!root) { document.body.insertAdjacentHTML('beforeend', '<div id="prompt-root"></div>'); root = $('#prompt-root'); }
  let body = '', foot = '';
  if (p.kind === 'choice') {
    const det = p.details || {};
    const answers = Object.entries(det.answers || {});
    const unresolved = det.unresolved || [];
    body = `<div class="callout info">${icon('info')}<div style="white-space:pre-wrap">${esc(p.message)}</div></div>
      ${unresolved.length ? `<div class="callout warn" style="margin-top:12px">${icon('alert')}<div><b>Couldn't answer automatically:</b><ul style="margin:6px 0 0;padding-left:18px">${unresolved.map((u) => `<li>${esc(u)}</li>`).join('')}</ul>
        <div class="tiny" style="margin-top:6px">Fill these in the browser window before submitting.</div></div></div>` : ''}
      ${answers.length ? `<div class="section-title" style="margin-top:16px">Answers filled in (${answers.length})</div>
        <div class="answers-list">${answers.map(([q, a]) => `<div><span class="q">${esc(q)}</span><span>${esc(a)}</span></div>`).join('')}</div>` : ''}
      <p class="small muted" style="margin-bottom:0">Check the browser window — you can edit anything there before choosing.</p>`;
    foot = p.choices.map((c, i) => `<button class="btn ${i === 0 ? 'primary' : c.value === 'n' ? 'danger' : 'ghost'}" data-act="prompt-answer" data-value="${esc(c.value)}">${esc(c.label)}</button>`).reverse().join('');
  } else {
    const opts = p.options || [];
    const multi = p.field_kind === 'checkbox_group';
    let input;
    if (opts.length) {
      input = `${opts.length > 10 ? '<input class="input" id="p-filter" placeholder="Filter options…" style="margin-bottom:8px">' : ''}
        <div class="opt-list" id="p-opts">${opts.map((o, i) => `<label class="opt"><input type="${multi ? 'checkbox' : 'radio'}" name="p-opt" value="${esc(o)}" ${i === 0 && !multi ? '' : ''}><span>${esc(o)}</span></label>`).join('')}</div>`;
    } else if (p.field_kind === 'textarea') {
      input = '<textarea class="input" id="p-text" rows="6" placeholder="Type your answer…"></textarea>';
    } else {
      input = '<input class="input" id="p-text" placeholder="Type your answer…">';
    }
    body = `<p style="margin-top:0;font-weight:600;font-size:15px">${esc(p.message)}${p.required ? ' <span class="pill st-failed">Required</span>' : ''}</p>
      ${input}
      <p class="tiny muted" style="margin-bottom:0">Your answer is saved to your Answers and reused automatically next time.</p>`;
    foot = `<button class="btn ghost" data-act="prompt-skip">Skip question</button>
      <button class="btn primary" data-act="prompt-field">${icon('check')} Use this answer</button>`;
  }
  root.innerHTML = `<div class="modal-wrap prompt"><div class="modal${p.kind === 'choice' ? ' wide' : ''}" role="alertdialog" aria-modal="true">
      <div class="modal-head"><span class="modal-icon">${icon('hand')}</span><h3>${esc(p.title || 'Your turn')}</h3></div>
      <div class="modal-body">${body}</div><div class="modal-foot">${foot}</div></div></div>`;
  const f = root.querySelector('#p-text, #p-filter, .modal-foot .btn.primary');
  if (f) setTimeout(() => f.focus(), 50);
  const filter = $('#p-filter');
  if (filter) filter.oninput = () => {
    const q = filter.value.toLowerCase();
    $$('#p-opts .opt').forEach((o) => { o.style.display = o.textContent.toLowerCase().includes(q) ? '' : 'none'; });
  };
  const Notification = window.Notification;
  if (Notification && Notification.permission === 'granted' && document.hidden) {
    try { new Notification('ApplyBot needs you', { body: p.message.slice(0, 140) }); } catch (_) { /* ignore */ }
  }
}
function closePrompt() { const r = $('#prompt-root'); if (r) r.innerHTML = ''; S.promptShown = null; }

async function answerPrompt(value) {
  const id = S.task && S.task.prompt && S.task.prompt.id;
  if (!id) { closePrompt(); return; }
  $('#prompt-root').innerHTML = '';
  try { await api('/api/task/answer', { id, value }); } catch (e) { fail(e); }
  pollSoon(100);
}
function fieldPromptValue() {
  const p = S.task && S.task.prompt;
  if (!p) return null;
  const txt = $('#p-text');
  if (txt) return txt.value.trim();
  const checked = $$('#p-opts input:checked').map((i) => i.value);
  if (p.field_kind === 'checkbox_group') return checked.length ? JSON.stringify(checked) : '';
  return checked[0] || '';
}

/* ----------------------------------------------------------- tag inputs */
function tagInput(id, values, placeholder = 'Type and press Enter') {
  S.tags[id] = (values || []).map(String);
  return `<div class="tags" data-tags="${id}">${tagChips(id)}<input placeholder="${esc(placeholder)}"></div>`;
}
const tagChips = (id) => S.tags[id].map((v, i) => `<span class="tag">${esc(v)}<button type="button" data-act="tag-del" data-i="${i}" title="Remove">×</button></span>`).join('');
function rerenderTags(box) {
  const id = box.dataset.tags;
  $$('.tag', box).forEach((t) => t.remove());
  box.querySelector('input').insertAdjacentHTML('beforebegin', tagChips(id));
}
function addTag(box, raw) {
  const id = box.dataset.tags;
  const vals = String(raw).split(',').map((v) => v.trim()).filter(Boolean);
  let changed = false;
  for (const v of vals) if (!S.tags[id].some((x) => x.toLowerCase() === v.toLowerCase())) { S.tags[id].push(v); changed = true; }
  if (changed) { rerenderTags(box); setDirty(); box.dispatchEvent(new Event('change', { bubbles: true })); }
}

/* ----------------------------------------------------------- job drawer */
async function openJob(id, refresh = false) {
  S.drawerId = id;
  const ov = $('#overlay');
  if (!refresh || !$('.drawer', ov)) {
    ov.innerHTML = `<div class="scrim" data-act="close-drawer"></div><aside class="drawer"><div class="drawer-body">
      <div class="skeleton" style="height:64px"></div><div class="skeleton" style="height:200px;margin-top:16px"></div></div></aside>`;
  }
  let j;
  try { j = await api('/api/job?id=' + encodeURIComponent(id)); } catch (e) { fail(e); closeDrawer(); return; }
  if (S.drawerId !== id) return;
  const docs = j.docs.filter((d) => d.ext !== 'png');
  const shots = j.docs.filter((d) => d.ext === 'png');
  const link = j.apply_url || j.url;
  const facts = [
    ['Location', j.location], ['Type', j.job_type], ['Remote', j.remote === null || j.remote === undefined ? '' : j.remote ? 'Yes' : 'No'],
    ['Posted', j.posted_at ? `${timeAgo(j.posted_at)} (${esc(String(j.posted_at).slice(0, 10))})` : ''], ['Source', j.source],
    ['Found', fmtDate(j.created_at)], ['Updated', fmtDate(j.updated_at)],
  ].filter(([, v]) => v);
  $('.drawer', ov).innerHTML = `
    <div class="drawer-head">
      ${avatar(j.company, true)}
      <div class="grow"><h2>${esc(j.title)}</h2><div class="muted">${esc(j.company)}${j.location ? ' · ' + esc(j.location) : ''}</div>
        <div class="row" style="margin-top:8px;flex-wrap:wrap">${pill(j.status)} ${scoreBadge(j.score)} <span class="chip">${esc(j.source)}</span></div></div>
      <button class="icon-btn" data-act="close-drawer" title="Close (Esc)">${icon('x')}</button>
    </div>
    <div class="drawer-body">
      <div class="row" style="flex-wrap:wrap;gap:8px">
        <button class="btn primary" data-act="apply-one" data-id="${esc(j.id)}">${icon('send')} Apply</button>
        <button class="btn" data-act="tailor-one" data-id="${esc(j.id)}">${icon('sparkles')} ${docs.length ? 'Re-tailor résumé' : 'Tailor résumé'}</button>
        ${link ? `<button class="btn ghost" data-act="open-url" data-url="${esc(link)}">${icon('external')} Open posting</button>` : ''}
        <div class="spacer"></div>
        <select class="input" style="width:auto" data-act-change="mark-one" data-id="${esc(j.id)}" title="Change status">
          <option value="">Mark as…</option>${['matched', 'applied', 'interviewing', 'offer', 'rejected_by_company', 'skipped', 'rejected', 'needs_review', 'new'].map((s) => `<option value="${s}">${STATUS_LABEL[s]}</option>`).join('')}
        </select>
      </div>
      ${j.score_reason ? `<div class="section-title">Why it ${j.score >= ((S.state && S.state.min_score) || 60) ? 'matches' : 'scored this way'}</div><div class="callout ${j.score >= 75 ? 'ok' : j.score >= 55 ? 'info' : 'warn'}">${icon('target')}<div>${esc(j.score_reason)}</div></div>` : ''}
      <div class="section-title">Documents ${j.doc_dir ? `<button class="btn ghost sm" style="float:right" data-act="open-path" data-path="${esc(j.doc_dir)}">${icon('folder')} Open folder</button>` : ''}</div>
      ${docs.length ? `<div class="docs">${docs.map((d) => `<button class="doc" data-act="open-path" data-path="${esc(d.path)}" title="Open ${esc(d.name)}">
          <span class="ext ext-${esc(d.ext)}">${esc(d.ext)}</span><span class="nm">${esc(d.name)}</span><span class="tiny faint">${fmtSize(d.size)}</span></button>`).join('')}</div>`
        : '<p class="small muted">No tailored documents yet. Click <b>Tailor résumé</b> to generate a résumé and cover letter for this job.</p>'}
      ${shots.length ? `<div class="section-title">Screenshots</div><div class="shots">${shots.map((d) => `<img src="/files/${encodeURI(d.path)}?t=${d.mtime}" alt="${esc(d.name)}" title="${esc(d.name)}" data-act="lightbox" loading="lazy">`).join('')}</div>` : ''}
      ${j.applications.length ? `<div class="section-title">Application history</div><div class="list">${j.applications.map((a) => `
          <div class="li">${pill(a.status)}<div class="grow"><div class="t1">${esc(STATUS_LABEL[a.mode] || a.mode || '')}</div><div class="t2">${esc(a.notes || '')}</div></div><span class="tiny faint" title="${esc(fmtDate(a.created_at))}">${timeAgo(a.created_at)}</span></div>`).join('')}</div>` : ''}
      <div class="section-title">Details</div>
      <dl class="kv">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
      ${j.description ? `<div class="section-title">Description</div><div class="desc">${esc(j.description)}</div>` : ''}
    </div>`;
}
function closeDrawer() { S.drawerId = null; $('#overlay').innerHTML = ''; }

/* ----------------------------------------------------------------- actions */
const ACTIONS = {
  'modal-close': () => closeModal(),
  'modal-bg': (el, e) => { if (e.target === el) closeModal(); },
  'close-drawer': () => closeDrawer(),
  'go': (el) => go(el.dataset.page),
  'theme': () => {
    const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = t;
    localStorage.setItem('ab-theme', t);
    renderThemeBtn();
  },
  'search': () => startTask('search', {}, { msg: 'Searching job boards…' }),
  'score': () => startTask('score', {}, { msg: 'Scoring new jobs…' }),
  'rescore': () => { if (confirm('Re-score every job, including ones already scored? This uses AI credits.')) startTask('score', { rescore: true, limit: 2000 }, { msg: 'Re-scoring…' }); },
  'run-modal': () => openRunModal(),
  'install-browser': () => startTask('install_browser', {}, { msg: 'Downloading the browser…' }),
  'stop-task': async () => { try { await api('/api/task/stop', {}); toast('Stopping…'); pollSoon(100); } catch (e) { fail(e); } },
  'reprompt': () => { if (S.task && S.task.prompt) showPrompt(S.task.prompt); },
  'job': (el) => openJob(el.dataset.id),
  'stop': () => {},
  'apply-one': (el) => openApplyModal([el.dataset.id], 'Apply to this job'),
  'tailor-one': (el) => startTask('tailor', { ids: [el.dataset.id] }, { msg: 'Tailoring résumé… (see Activity for progress)' }),
  'open-url': (el) => api('/api/open', { url: el.dataset.url }).catch(fail),
  'open-path': (el) => api('/api/open', { path: el.dataset.path }).catch(fail),
  'open-data': () => api('/api/open', { path: 'data_dir' }).catch(fail),
  'lightbox': (el) => {
    $('#overlay').insertAdjacentHTML('beforeend', `<div class="lightbox" data-act="lightbox-close"><img src="${esc(el.getAttribute('src'))}" alt=""></div>`);
  },
  'lightbox-close': (el) => el.remove(),
  'pick-mode': (el) => {
    $$('.mode-card', el.parentElement).forEach((c) => c.classList.toggle('on', c === el));
    el.parentElement.dispatchEvent(new Event('modechange', { bubbles: true }));
  },
  'prompt-answer': (el) => answerPrompt(el.dataset.value),
  'prompt-field': () => answerPrompt(fieldPromptValue()),
  'prompt-skip': () => answerPrompt(''),
  'tag-del': (el) => {
    const box = el.closest('.tags');
    S.tags[box.dataset.tags].splice(Number(el.dataset.i), 1);
    rerenderTags(box);
    setDirty();
    box.dispatchEvent(new Event('change', { bubbles: true }));
  },
  'tags-focus': () => {},
};

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (el && ACTIONS[el.dataset.act]) {
    if (el.tagName === 'A' && el.getAttribute('href') === '#') e.preventDefault();
    ACTIONS[el.dataset.act](el, e);
    return;
  }
  const tags = e.target.closest('.tags');
  if (tags && e.target === tags) tags.querySelector('input').focus();
});
document.addEventListener('change', (e) => {
  const el = e.target.closest('[data-act-change]');
  if (el && ACTIONS[el.dataset.actChange]) ACTIONS[el.dataset.actChange](el, e);
});
ACTIONS['mark-one'] = async (el) => {
  if (!el.value) return;
  try {
    await api('/api/jobs/mark', { ids: [el.dataset.id], status: el.value });
    toast(`Marked as ${STATUS_LABEL[el.value]}`, 'ok');
    openJob(el.dataset.id, true);
    loadState().catch(() => {});
    if (S.page === 'jobs') PAGES.jobs.refresh?.();
  } catch (err) { fail(err); }
};

document.addEventListener('keydown', (e) => {
  const t = e.target;
  if (t.matches && t.matches('.tags input')) {
    const box = t.closest('.tags');
    if ((e.key === 'Enter' || e.key === ',' || e.key === 'Tab') && t.value.trim()) {
      e.preventDefault();
      addTag(box, t.value);
      t.value = '';
    } else if (e.key === 'Backspace' && !t.value && S.tags[box.dataset.tags].length) {
      S.tags[box.dataset.tags].pop();
      rerenderTags(box);
      setDirty();
    }
    return;
  }
  if ($('#prompt-root .modal')) {
    if (e.key === 'Enter' && !e.shiftKey && t.id === 'p-text' && t.tagName === 'INPUT') { e.preventDefault(); answerPrompt(fieldPromptValue()); }
    return;
  }
  if (e.key === 'Escape') {
    const lb = $('.lightbox');
    if (lb) { lb.remove(); return; }
    if ($('#modal .modal')) { closeModal(); return; }
    if (S.drawerId) { closeDrawer(); return; }
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    const btn = $('[data-save]');
    if (btn) { e.preventDefault(); btn.click(); }
  }
});
document.addEventListener('focusout', (e) => {
  const t = e.target;
  if (t.matches && t.matches('.tags input') && t.value.trim()) { addTag(t.closest('.tags'), t.value); t.value = ''; }
});

function renderThemeBtn() {
  $('#theme-btn').innerHTML = icon(document.documentElement.dataset.theme === 'dark' ? 'sun' : 'moon');
}

/* -------------------------------------------------------------------- boot */
async function boot() {
  $('#theme-btn').dataset.act = 'theme';
  renderThemeBtn();
  window.addEventListener('hashchange', route);
  window.addEventListener('pagehide', () => { try { navigator.sendBeacon('/api/bye', '{}'); } catch (_) { /* ignore */ } });
  try { await loadState(); } catch (e) { /* the page will show the error */ }
  route();
  poll();
  setInterval(() => { if (S.task && S.task.status === 'running') { renderTaskPill(); const el = $('#task-elapsed'); if (el) el.textContent = duration(Date.now() / 1000 - S.task.started); } }, 1000);
}
