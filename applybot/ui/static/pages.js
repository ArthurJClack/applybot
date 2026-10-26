'use strict';
/* ApplyBot UI - pages: dashboard, jobs, apply-to-link, activity, profile, answers. */

/* ============================================================== dashboard */
PAGES.dashboard = {
  title: 'Dashboard', icon: 'dashboard',
  async render(main) {
    const [st, top, apps] = await Promise.all([
      loadState(),
      api('/api/jobs?status=matched&sort=score&limit=6'),
      api('/api/applications?limit=7'),
    ]);
    const c = st.counts || {};
    const first = (st.name || '').trim().split(/\s+/)[0];
    const h = new Date().getHours();
    const greet = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
    const su = st.setup || {};
    const answersSeen = localStorage.getItem('ab-answers-reviewed') === '1';
    const steps = [
      { done: su.profile && !su.sample_profile, t: 'Add your experience', d: su.sample_profile ? 'Your profile still holds the sample résumé. Replace it with yours.' : 'Write everything about you — jobs, projects, skills. One plain text file.', b: 'Edit profile', act: 'go', page: 'profile' },
      { done: su.ai || su.ai_off, t: 'Connect an AI model', d: 'OpenAI, Claude, Gemini, or free local Ollama. Or turn AI off for keyword matching.', b: 'Set up AI', act: 'go', page: 'settings' },
      { done: answersSeen, t: 'Review your standard answers', d: 'Work authorization, sponsorship, start date, and voluntary EEO questions.', b: 'Review', act: 'go', page: 'answers' },
      { done: su.browser, t: 'Install the form-filling browser', d: 'A one-time ~150 MB download used to fill out applications.', b: 'Install', act: 'install-browser' },
      { done: su.jobs, t: 'Find your first jobs', d: 'Search internship and job boards that match your keywords.', b: 'Find jobs', act: 'search' },
    ];
    const doneCount = steps.filter((s) => s.done).length;
    const a = st.apply || {};
    const pipeline = [
      ['Found', st.total, 'blue'], ['Matched', (c.matched || 0) + (c.tailored || 0) + (c.applied || 0), 'indigo'],
      ['Tailored', (c.tailored || 0) + (c.applied || 0), 'amber'], ['Applied', c.applied || 0, 'green'],
    ];
    const pmax = Math.max(1, ...pipeline.map((p) => p[1] || 0));
    const modeName = (MODES.find((m) => m.id === a.mode) || {}).t || a.mode;

    main.innerHTML = `<div class="page">
      <section class="hero">
        <div>
          <div class="tiny" style="opacity:.85;text-transform:uppercase;letter-spacing:.08em;font-weight:700">${greet}${first ? ', ' + esc(first) : ''}</div>
          <h1>Let's land your next role.</h1>
          <p>ApplyBot finds postings, scores them against your profile, tailors your résumé for each one, and fills out the application — you stay in control.</p>
          <div class="row" style="flex-wrap:wrap;gap:10px;margin-top:18px">
            <button class="btn white lg" data-act="run-modal">${icon('rocket')} Run autopilot</button>
            <button class="btn glass lg" data-act="search">${icon('search')} Find jobs</button>
            <button class="btn glass lg" data-act="go" data-page="apply">${icon('link')} Apply to a link</button>
          </div>
        </div>
        <div class="hero-side tiny">
          <div><b>Mode</b> ${esc(modeName)}</div>
          <div><b>AI</b> ${st.ai.available ? esc(st.ai.provider + ' · ' + (st.ai.model || '')) : st.ai.provider === 'none' ? 'Off' : 'Not connected'}</div>
          <div><b>Today</b> ${st.applied_today || 0} / ${a.max_per_day} applications</div>
        </div>
      </section>

      <div class="grid g-4">
        ${stat('Jobs tracked', st.total, st.new_today ? `+${st.new_today} found today` : 'across all sources', 'jobs', 'blue', 'jobs', '')}
        ${stat('Strong matches', c.matched || 0, `score ≥ ${st.min_score}, ready to apply`, 'target', 'indigo', 'jobs')}
        ${stat('Applied', st.total_applied || 0, `${st.applied_today || 0} today`, 'send', 'green', 'activity')}
        ${stat('Needs review', c.needs_review || 0, 'waiting on you', 'hand', 'amber', 'jobs', 'needs_review')}
      </div>

      <div class="grid g-main">
        <div class="col">
          <div class="card">
            <div class="card-head"><h3>${icon('target')} Top matches</h3><div class="spacer"></div>
              <button class="btn ghost sm" data-act="go-jobs" data-status="matched">View all</button></div>
            ${top.jobs.length ? `<div class="list">${top.jobs.map(jobLi).join('')}</div>`
              : empty('target', 'No matches yet', st.total ? 'Score your jobs to find the best fits.' : 'Find jobs first, then ApplyBot scores them against your profile.',
                st.total ? `<button class="btn primary sm" data-act="score">${icon('sparkles')} Score jobs</button>` : `<button class="btn primary sm" data-act="search">${icon('search')} Find jobs</button>`)}
          </div>
          <div class="card">
            <div class="card-head"><h3>${icon('activity')} Recent applications</h3><div class="spacer"></div>
              <button class="btn ghost sm" data-act="go" data-page="activity">Activity</button></div>
            ${apps.applications.length ? `<div class="list">${apps.applications.map(appLi).join('')}</div>`
              : empty('send', 'Nothing sent yet', 'Your applications and dry runs will show up here.')}
          </div>
        </div>
        <div class="col">
          ${doneCount < steps.length ? `<div class="card">
            <div class="card-head"><h3>${icon('checkCircle')} Get set up</h3><div class="spacer"></div><span class="tiny muted">${doneCount} of ${steps.length}</span></div>
            <div class="card-body">
              <div class="bar" style="margin-bottom:12px"><span style="width:${(doneCount / steps.length) * 100}%"></span></div>
              ${steps.map((s) => `<div class="check-item${s.done ? ' done' : ''}">
                <span class="check-dot">${s.done ? icon('check', 'sm') : ''}</span>
                <div class="grow"><div class="ci-title">${s.t}</div>${s.done ? '' : `<div class="tiny muted">${s.d}</div>`}</div>
                ${s.done ? '' : `<button class="btn sm" data-act="${s.act}" ${s.page ? `data-page="${s.page}"` : ''}>${s.b}</button>`}
              </div>`).join('')}
            </div></div>` : ''}
          <div class="card">
            <div class="card-head"><h3>${icon('sliders')} Pipeline</h3></div>
            <div class="card-body"><div class="bars">${pipeline.map(([l, n, col]) => `
              <div class="bar-row"><span class="small">${l}</span><div class="bar ${col}"><span style="width:${((n || 0) / pmax) * 100}%"></span></div><b class="small">${n || 0}</b></div>`).join('')}
            </div>
            <div class="row" style="margin-top:14px;gap:8px;flex-wrap:wrap">
              <button class="btn sm" data-act="score">${icon('sparkles')} Score new jobs</button>
              <button class="btn sm ghost" data-act="go-jobs" data-status="">${icon('jobs')} Browse jobs</button>
            </div></div>
          </div>
          <div class="card card-pad">
            <div class="row">${icon('folder')}<div class="grow"><div class="small"><b>Your data folder</b></div><div class="tiny muted mono clip" title="${esc(st.data_dir)}">${esc(st.data_dir)}</div></div>
            <button class="btn ghost sm" data-act="open-data">Open</button></div>
          </div>
        </div>
      </div>
    </div>`;
  },
  refresh() { if (S.page === 'dashboard' && !$('#modal .modal')) PAGES.dashboard.render($('#main')); },
};

function stat(label, value, hint, ic, color, page, status) {
  return `<button class="card stat" data-act="${page === 'jobs' ? 'go-jobs' : 'go'}" data-page="${page}" ${status !== undefined ? `data-status="${status}"` : ''}>
    <span class="glyph ${color}">${icon(ic)}</span>
    <span><span class="label">${label}</span><span class="value">${value ?? 0}</span><span class="hint">${hint}</span></span></button>`;
}
function empty(ic, title, text, action = '') {
  return `<div class="empty">${icon(ic, 'lg')}<b>${title}</b><span class="small muted">${text}</span>${action}</div>`;
}
function jobLi(j) {
  return `<div class="li" data-act="job" data-id="${esc(j.id)}" role="button" tabindex="0">${avatar(j.company)}
    <div class="grow"><div class="t1 clip">${esc(j.title)}</div><div class="t2 clip">${esc(j.company)}${j.location ? ' · ' + esc(j.location) : ''}</div></div>
    ${scoreBadge(j.score)}</div>`;
}
function appLi(a) {
  return `<div class="li" ${a.job_id ? `data-act="job" data-id="${esc(a.job_id)}" role="button"` : ''}>${avatar(a.company || '?')}
    <div class="grow"><div class="t1 clip">${esc(a.title || a.url || 'Application')}</div><div class="t2 clip">${esc(a.company || '')}${a.notes ? ' · ' + esc(a.notes) : ''}</div></div>
    <div style="text-align:right">${pill(a.status)}<div class="tiny faint" title="${esc(fmtDate(a.created_at))}">${timeAgo(a.created_at)}</div></div></div>`;
}
ACTIONS['go-jobs'] = (el) => {
  S.jobs.f.status = el.dataset.status ?? 'matched';
  S.jobs.sel.clear();
  if (S.page === 'jobs') PAGES.jobs.render($('#main')); else go('jobs');
};

/* =================================================================== jobs */
const JOB_TABS = [['', 'All'], ['matched', 'Matched'], ['new', 'New'], ['tailored', 'Tailored'], ['applied', 'Applied'],
  ['interviewing', 'Interviewing'], ['offer', 'Offers'], ['rejected_by_company', 'Rejected by co.'],
  ['needs_review', 'Needs review'], ['failed', 'Failed'], ['skipped', 'Skipped'], ['rejected', 'Low match']];

PAGES.jobs = {
  title: 'Jobs', icon: 'jobs',
  async render(main) {
    const st = S.state || await loadState();
    const f = S.jobs.f;
    main.innerHTML = `<div class="page">
      <div class="page-head">
        <div><h1>Jobs</h1><p id="jobs-sub" class="muted">Everything ApplyBot has found. Click a job for details, documents and screenshots.</p></div>
        <div class="row" style="gap:8px">
          <button class="btn" data-act="score" title="Score jobs that haven't been scored yet">${icon('sparkles')} Score new</button>
          <button class="btn primary" data-act="search">${icon('search')} Find jobs</button>
        </div>
      </div>
      <div class="tabs" id="job-tabs"></div>
      <div class="row toolbar" style="gap:10px;flex-wrap:wrap;margin:14px 0">
        <div class="search-wrap" style="flex:1;min-width:220px">${icon('search')}<input class="input" id="jf-q" placeholder="Search company, title or location…" value="${esc(f.q)}"></div>
        <select class="input" id="jf-source" style="width:auto"><option value="">All sources</option>
          ${(st.sources || []).map((s) => `<option ${s === f.source ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select>
        <select class="input" id="jf-min" style="width:auto">
          ${[['', 'Any score'], ['50', 'Score 50+'], ['60', 'Score 60+'], ['70', 'Score 70+'], ['80', 'Score 80+'], ['90', 'Score 90+']].map(([v, l]) => `<option value="${v}" ${v === f.min_score ? 'selected' : ''}>${l}</option>`).join('')}</select>
        <select class="input" id="jf-sort" style="width:auto">
          ${[['score', 'Best match'], ['newest', 'Newest posted'], ['updated', 'Recently updated'], ['company', 'Company A–Z']].map(([v, l]) => `<option value="${v}" ${v === f.sort ? 'selected' : ''}>${l}</option>`).join('')}</select>
      </div>
      <div id="bulk"></div>
      <div class="card table-wrap" id="job-table"><div class="skeleton" style="height:240px"></div></div>
    </div>`;
    let t;
    $('#jf-q').oninput = (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value; loadJobs(); }, 220); };
    $('#jf-source').onchange = (e) => { f.source = e.target.value; loadJobs(); };
    $('#jf-min').onchange = (e) => { f.min_score = e.target.value; loadJobs(); };
    $('#jf-sort').onchange = (e) => { f.sort = e.target.value; loadJobs(); };
    await loadJobs();
  },
  refresh() { if (S.page === 'jobs') loadJobs(); },
};

async function loadJobs() {
  const f = S.jobs.f;
  const qs = new URLSearchParams({ ...f, limit: 1000 });
  const d = await api('/api/jobs?' + qs);
  S.jobs.list = d.jobs;
  S.jobs.total = d.total;
  S.jobs.tabs = d.tab_counts;
  const ids = new Set(d.jobs.map((j) => j.id));
  for (const id of [...S.jobs.sel]) if (!ids.has(id)) S.jobs.sel.delete(id);
  renderJobTabs();
  renderJobTable();
  renderBulk();
}

function renderJobTabs() {
  const tc = S.jobs.tabs;
  const all = Object.values(tc).reduce((a, b) => a + b, 0);
  const el = $('#job-tabs');
  if (!el) return;
  el.innerHTML = JOB_TABS.map(([s, l]) => {
    const n = s ? (tc[s] || 0) : all;
    if (s && !n && !['matched', 'new', 'applied'].includes(s) && S.jobs.f.status !== s) return '';
    return `<button class="${S.jobs.f.status === s ? 'on' : ''}" data-act="job-tab" data-status="${s}">${l}<span class="n">${n}</span></button>`;
  }).join('');
}
ACTIONS['job-tab'] = (el) => { S.jobs.f.status = el.dataset.status; S.jobs.sel.clear(); renderJobTabs(); loadJobs(); };

function renderJobTable() {
  const el = $('#job-table');
  if (!el) return;
  const list = S.jobs.list;
  const f = S.jobs.f;
  if (!list.length) {
    const filtered = f.q || f.source || f.min_score;
    el.innerHTML = filtered ? empty('search', 'No jobs match these filters', 'Try clearing the search or lowering the minimum score.')
      : f.status === 'matched' ? empty('target', 'No matched jobs yet', 'Find jobs, then score them — strong matches land here.',
        `<div class="row" style="gap:8px"><button class="btn sm" data-act="score">${icon('sparkles')} Score jobs</button><button class="btn primary sm" data-act="search">${icon('search')} Find jobs</button></div>`)
      : empty('inbox', 'Nothing here', 'No jobs with this status.');
    return;
  }
  const allSel = list.every((j) => S.jobs.sel.has(j.id));
  el.innerHTML = `<table class="tbl">
    <thead><tr>
      <th style="width:36px"><input type="checkbox" class="check" id="sel-all" ${allSel ? 'checked' : ''} title="Select all"></th>
      <th>Role</th><th>Location</th><th style="width:70px">Score</th><th style="width:120px">Status</th><th style="width:100px">Posted</th>
    </tr></thead>
    <tbody>${list.map((j) => `<tr data-act="job" data-id="${esc(j.id)}" class="${S.jobs.sel.has(j.id) ? 'sel' : ''}">
      <td data-act="stop"><input type="checkbox" class="check rowcheck" data-id="${esc(j.id)}" ${S.jobs.sel.has(j.id) ? 'checked' : ''}></td>
      <td><div class="row" style="gap:10px">${avatar(j.company)}<div style="min-width:0"><div class="role clip">${esc(j.title)}</div>
        <div class="co clip">${esc(j.company)} <span class="faint">· ${esc(j.source)}</span>${j.job_type ? ` <span class="faint">· ${esc(j.job_type)}</span>` : ''}</div></div></div></td>
      <td><div class="clip small" style="max-width:220px" title="${esc(j.location || '')}">${esc(j.location || '—')}${j.remote ? ' <span class="chip">Remote</span>' : ''}</div></td>
      <td>${scoreBadge(j.score)}</td>
      <td>${pill(j.status)}</td>
      <td class="small muted" title="${esc(j.posted_at || '')}">${j.posted_at ? timeAgo(j.posted_at) : '—'}</td>
    </tr>`).join('')}</tbody></table>
    ${S.jobs.total > list.length ? `<div class="small muted" style="padding:12px 16px">Showing ${list.length} of ${S.jobs.total}. Narrow the search to see more.</div>` : ''}`;
  $('#jobs-sub').textContent = `${plural(S.jobs.total, 'job')} in this view. Click a job for details, documents and screenshots.`;
  $('#sel-all').onchange = (e) => {
    list.forEach((j) => (e.target.checked ? S.jobs.sel.add(j.id) : S.jobs.sel.delete(j.id)));
    renderJobTable(); renderBulk();
  };
}
document.addEventListener('change', (e) => {
  if (!e.target.classList.contains('rowcheck')) return;
  const id = e.target.dataset.id;
  if (e.target.checked) S.jobs.sel.add(id); else S.jobs.sel.delete(id);
  e.target.closest('tr').classList.toggle('sel', e.target.checked);
  const all = $('#sel-all');
  if (all) all.checked = S.jobs.list.every((j) => S.jobs.sel.has(j.id));
  renderBulk();
});

function renderBulk() {
  const el = $('#bulk');
  if (!el) return;
  const n = S.jobs.sel.size;
  if (!n) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="bulkbar"><b>${plural(n, 'job')} selected</b><div class="spacer"></div>
    <button class="btn sm" data-act="bulk-tailor">${icon('sparkles')} Tailor résumés</button>
    <button class="btn sm primary" data-act="bulk-apply">${icon('send')} Apply</button>
    <select class="input sm" style="width:auto" data-act-change="bulk-mark"><option value="">Mark as…</option>
      ${['matched', 'applied', 'skipped', 'rejected', 'needs_review', 'new'].map((s) => `<option value="${s}">${STATUS_LABEL[s]}</option>`).join('')}</select>
    <button class="btn sm ghost" data-act="bulk-clear">Clear</button></div>`;
}
ACTIONS['bulk-clear'] = () => { S.jobs.sel.clear(); renderJobTable(); renderBulk(); };
ACTIONS['bulk-tailor'] = () => startTask('tailor', { ids: [...S.jobs.sel] }, { msg: `Tailoring ${plural(S.jobs.sel.size, 'résumé')}…`, navigate: false }).then((ok) => ok && go('activity'));
ACTIONS['bulk-apply'] = () => openApplyModal([...S.jobs.sel]);
ACTIONS['bulk-mark'] = async (el) => {
  if (!el.value) return;
  try {
    await api('/api/jobs/mark', { ids: [...S.jobs.sel], status: el.value });
    toast(`Marked ${plural(S.jobs.sel.size, 'job')} as ${STATUS_LABEL[el.value]}`, 'ok');
    S.jobs.sel.clear();
    loadState().catch(() => {});
    loadJobs();
  } catch (e) { fail(e); }
};
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target.matches && e.target.matches('.li[data-act="job"]')) e.target.click();
});

/* ========================================================== apply to link */
PAGES.apply = {
  title: 'Apply to a link', icon: 'link',
  async render(main) {
    const st = S.state || await loadState();
    const a = st.apply || {};
    main.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>Apply to a link</h1>
        <p class="muted">Found a posting yourself? Paste the link — ApplyBot tailors your résumé for it and fills out the form.</p></div></div>
      <div class="grid g-main">
        <div class="card"><div class="card-body">
          <div class="form-grid">
            <label class="full">Application or posting URL<input class="input" id="u-url" placeholder="https://boards.greenhouse.io/company/jobs/123…" autofocus></label>
            <label>Company <span class="faint">(optional)</span><input class="input" id="u-company" placeholder="Detected from the page"></label>
            <label>Job title <span class="faint">(optional)</span><input class="input" id="u-title" placeholder="Detected from the page"></label>
            <label class="full">Job description <span class="faint">(optional — paste it for better tailoring)</span>
              <textarea class="input" id="u-desc" rows="6" placeholder="If left empty, ApplyBot reads it from the page."></textarea></label>
          </div>
          <div class="section-title">How should it apply?</div>
          ${modeCards(a.mode || 'review')}
          <div style="margin-top:14px">${switchHtml('u-headless', a.headless, 'Hide the browser window', 'Ignored in Review mode.')}</div>
          <div class="row" style="margin-top:18px"><div class="spacer"></div>
            <button class="btn primary lg" id="u-go">${icon('send')} Start application</button></div>
        </div></div>
        <div class="col">
          <div class="card card-pad">
            <h3 style="margin-top:0">${icon('globe')} Works with</h3>
            <div class="chips">${['Greenhouse', 'Lever', 'Ashby', 'Workday', 'SmartRecruiters', 'iCIMS', 'Workable', 'Jobvite', 'BambooHR', 'Custom forms'].map((s) => `<span class="chip">${s}</span>`).join('')}</div>
          </div>
          <div class="card card-pad small">
            <h3 style="margin-top:0">${icon('info')} Good to know</h3>
            <ul class="muted" style="padding-left:18px;margin:0;display:grid;gap:8px">
              <li>Sites that need an account: log in once in the browser window. ApplyBot remembers it next time.</li>
              <li>CAPTCHAs and questions it can't answer are handed to you — you'll get a pop-up here.</li>
              <li>Legal, sponsorship and demographic questions only use your <a href="#/answers">Answers</a>, never AI guesses.</li>
              <li>Résumé, cover letter and screenshot are saved per job in your data folder.</li>
            </ul>
          </div>
        </div>
      </div></div>`;
    $('#u-go').onclick = () => {
      const url = $('#u-url').value.trim();
      if (!/^https?:\/\/\S+\.\S+/.test(url)) { toast('Paste a full link starting with https://', 'err'); $('#u-url').focus(); return; }
      startTask('apply_url', {
        url, company: $('#u-company').value.trim(), title: $('#u-title').value.trim(), description: $('#u-desc').value.trim(),
        mode: pickedMode(main), headless: $('#u-headless').checked,
      }, { msg: 'Opening the application…' });
    };
  },
};

/* =============================================================== activity */
PAGES.activity = {
  title: 'Activity', icon: 'activity',
  async render(main) {
    main.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>Activity</h1><p class="muted">Live progress of the current task, and every application ApplyBot has made.</p></div></div>
      <div class="card"><div class="card-head" id="task-head"></div><div class="console" id="console"></div></div>
      <div class="card"><div class="card-head"><h3>${icon('send')} Applications</h3><div class="spacer"></div>
        <select class="input sm" id="app-filter" style="width:auto"><option value="">All results</option>
          ${['applied', 'dry_run', 'needs_review', 'failed', 'skipped'].map((s) => `<option value="${s}">${STATUS_LABEL[s]}</option>`).join('')}</select></div>
        <div class="table-wrap" id="apps"><div class="skeleton" style="height:160px"></div></div></div>
    </div>`;
    renderTaskHead();
    renderConsole();
    $('#app-filter').onchange = () => loadApps();
    await loadApps();
  },
  refresh() { if (S.page === 'activity') loadApps(); },
};

async function loadApps() {
  const el = $('#apps');
  if (!el) return;
  const d = await api('/api/applications?limit=500');
  const f = $('#app-filter')?.value;
  const rows = f ? d.applications.filter((a) => a.status === f) : d.applications;
  el.innerHTML = rows.length ? `<table class="tbl"><thead><tr><th>Job</th><th style="width:130px">Result</th><th style="width:110px">Mode</th><th>Notes</th><th style="width:110px">When</th></tr></thead>
    <tbody>${rows.map((a) => `<tr ${a.job_id ? `data-act="job" data-id="${esc(a.job_id)}"` : ''}>
      <td><div class="row" style="gap:10px">${avatar(a.company || '?')}<div style="min-width:0"><div class="role clip">${esc(a.title || a.url || '')}</div><div class="co clip">${esc(a.company || '')}</div></div></div></td>
      <td>${pill(a.status)}</td><td class="small">${esc(STATUS_LABEL[a.mode] || humanize(a.mode || ''))}</td>
      <td><div class="clip small muted" style="max-width:340px" title="${esc(a.notes || '')}">${esc(a.notes || '')}</div></td>
      <td class="small muted" title="${esc(fmtDate(a.created_at))}">${timeAgo(a.created_at)}</td></tr>`).join('')}</tbody></table>`
    : empty('send', 'No applications yet', 'Run autopilot or apply to jobs from the Jobs page.');
}

/* ================================================================ profile */
PAGES.profile = {
  title: 'Profile', icon: 'user',
  async render(main) {
    const f = await api('/api/file?name=profile');
    main.innerHTML = `<div class="page wide">
      <div class="page-head">
        <div><h1>Your profile</h1><p class="muted">Everything about you, in plain text. ApplyBot picks the most relevant parts for each job — it never invents anything.</p></div>
        <div class="row" style="gap:8px">
          <button class="btn ghost" data-act="open-path" data-path="${esc(f.path)}" title="Open in your text editor">${icon('external')} Open file</button>
          <button class="btn primary" id="pf-save" data-save>${icon('save')} Save</button>
        </div>
      </div>
      ${f.sample ? `<div class="callout warn">${icon('alert')}<div><b>This is a sample profile.</b> Replace it with your own details — keep the same headings (<span class="mono"># EXPERIENCE</span>, <span class="mono">## Title | Company</span>, <span class="mono">- bullet</span>) and ApplyBot understands it perfectly.</div></div>` : ''}
      <div class="grid g-2" style="align-items:start">
        <div class="card">
          <div class="card-head"><h3>${icon('file')} profile.txt</h3><div class="spacer"></div><span class="tiny faint" id="pf-state">Saved</span></div>
          <textarea class="editor" id="pf-text" spellcheck="true">${esc(f.text)}</textarea>
          <details class="more" style="padding:0 16px 14px"><summary class="small">Formatting guide</summary>
            <pre class="mono tiny" style="white-space:pre-wrap">${esc(PROFILE_GUIDE)}</pre></details>
        </div>
        <div class="card"><div class="card-head"><h3>${icon('eye')} What ApplyBot understood</h3><div class="spacer"></div>
          <button class="btn ghost sm" data-act="pf-refresh">${icon('refresh')} Refresh</button></div>
          <div class="card-body" id="pf-preview"><div class="skeleton" style="height:300px"></div></div></div>
      </div></div>`;
    const ta = $('#pf-text');
    ta.oninput = () => { setDirty(); $('#pf-state').textContent = 'Unsaved changes'; };
    ta.onkeydown = (e) => {
      if (e.key === 'Tab') { e.preventDefault(); document.execCommand('insertText', false, '  '); }
    };
    $('#pf-save').onclick = async () => {
      try {
        await api('/api/file', { name: 'profile', text: ta.value });
        setDirty(false);
        $('#pf-state').textContent = 'Saved';
        toast('Profile saved', 'ok');
        loadState().catch(() => {});
        loadPreview(true);
      } catch (e) { fail(e); }
    };
    loadPreview(false);
  },
};
ACTIONS['pf-refresh'] = () => loadPreview(true);

const PROFILE_GUIDE = `Name: Your Name
Email: you@example.com | Phone: 555-123-4567 | Location: City, ST
LinkedIn: linkedin.com/in/you | GitHub: github.com/you

# SUMMARY
One or two sentences about you.

# EDUCATION
## B.S. Computer Science | State University | Aug 2023 - May 2027
GPA: 3.8
- Relevant coursework: Data Structures, Algorithms

# EXPERIENCE
## Software Engineering Intern | Company | City, ST | May 2025 - Aug 2025
- Built X using Y, improving Z by 30%
(write as many bullets as you like — ApplyBot picks the best ones per job)

# PROJECTS
## Project Name | Python, React | github.com/you/project
- What it does and the impact

# SKILLS
Languages: Python, Java, TypeScript
Frameworks: React, Django

# PREFERENCES
Roles: software engineering internship
Locations: New York, Remote`;

async function loadPreview(refresh) {
  const el = $('#pf-preview');
  if (!el) return;
  if (refresh) el.innerHTML = '<div class="skeleton" style="height:300px"></div>';
  let p;
  try { p = await api('/api/profile/parsed' + (refresh ? '?refresh=1' : '')); } catch (e) { el.innerHTML = `<div class="callout err">${icon('alert')}<div>${esc(e.message)}</div></div>`; return; }
  if (!$('#pf-preview')) return;
  if (p.error) { el.innerHTML = `<div class="callout err">${icon('alert')}<div>${esc(p.error)}</div></div>`; return; }
  const c = p.contact || {};
  const entry = (h, s, bullets) => `<div class="pv-entry"><div class="h">${h}</div>${s ? `<div class="s">${s}</div>` : ''}${bullets && bullets.length ? `<ul>${bullets.map((b) => `<li>${esc(b)}</li>`).join('')}</ul>` : ''}</div>`;
  const sec = (title, items) => items ? `<div class="section-title">${title}</div>${items}` : '';
  const warn = [];
  if (!c.name) warn.push('No name found — add a "Name:" line at the top.');
  if (!c.email) warn.push('No email found.');
  if (!(p.experience || []).length && !(p.projects || []).length) warn.push('No experience or projects found — check the "## Title | Company | Dates" headings.');
  el.innerHTML = `
    ${warn.length ? `<div class="callout warn" style="margin-bottom:12px">${icon('alert')}<div>${warn.map(esc).join('<br>')}</div></div>` : ''}
    <div class="pv-name">${esc(c.name || 'Unnamed')}</div>
    <div class="small muted">${[c.email, c.phone, c.location].filter(Boolean).map(esc).join(' · ')}</div>
    <div class="small muted">${[c.linkedin, c.github, c.website].filter(Boolean).map(esc).join(' · ')}</div>
    ${p.summary ? `<p class="small">${esc(p.summary)}</p>` : ''}
    ${sec('Education', (p.education || []).map((e) => entry(esc(e.degree || e.school), [e.school !== e.degree ? e.school : '', e.dates, e.gpa ? 'GPA ' + e.gpa : ''].filter(Boolean).map(esc).join(' · '), e.details)).join(''))}
    ${sec(`Experience (${(p.experience || []).length})`, (p.experience || []).map((e) => entry(esc(e.title), [e.company, e.location, e.dates].filter(Boolean).map(esc).join(' · '), e.bullets)).join(''))}
    ${sec(`Projects (${(p.projects || []).length})`, (p.projects || []).map((e) => entry(esc(e.name), [e.tech, e.dates].filter(Boolean).map(esc).join(' · '), e.bullets)).join(''))}
    ${sec('Leadership', (p.leadership || []).map((e) => entry(esc(e.title), [e.company, e.dates].filter(Boolean).map(esc).join(' · '), e.bullets)).join(''))}
    ${(p.all_skills || []).length ? `<div class="section-title">Skills (${p.all_skills.length})</div><div class="chips">${p.all_skills.map((s) => `<span class="chip">${esc(s)}</span>`).join('')}</div>` : ''}
    ${(p.certifications || []).length ? sec('Certifications', `<ul class="small">${p.certifications.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`) : ''}
    ${p.awards && (Array.isArray(p.awards) ? p.awards.length : true) ? sec('Awards', `<ul class="small">${[].concat(p.awards).map((x) => `<li>${esc(typeof x === 'string' ? x : JSON.stringify(x))}</li>`).join('')}</ul>`) : ''}
    ${p.preferences && Object.keys(p.preferences).length ? sec('Preferences', `<dl class="kv">${Object.entries(p.preferences).map(([k, v]) => `<dt>${esc(humanize(k))}</dt><dd>${esc(Array.isArray(v) ? v.join(', ') : v)}</dd>`).join('')}</dl>`) : ''}`;
}

/* ================================================================ answers */
const ANSWER_SECTIONS = [
  { key: 'basics', title: 'Basics', icon: 'user', desc: 'Address and current-role details used to fill contact sections.' },
  { key: 'work_authorization', title: 'Work authorization', icon: 'shield', desc: 'Never guessed by AI. Answered only from here.' },
  { key: 'logistics', title: 'Logistics', icon: 'clock', desc: 'Start date, salary, relocation and how you heard about the role.' },
  { key: 'eeo', title: 'Voluntary self-identification', icon: 'info', desc: 'Defaults decline to answer. Change only if you want to disclose.' },
  { key: 'sensitive', title: 'Legal & background', icon: 'alert', desc: 'Leave blank to be asked whenever a form requires it.' },
  { key: 'files', title: 'Extra files', icon: 'file', desc: 'Full paths to files uploaded when a form asks for them.' },
];
const ANSWER_SUGGEST = {
  authorized_to_work: ['Yes', 'No'], requires_sponsorship: ['No', 'Yes'], willing_to_relocate: ['Yes', 'No'], in_person_ok: ['Yes', 'No'],
  over_18: ['Yes', 'No'], previously_employed_here: ['No', 'Yes'], background_check_ok: ['Yes', 'No'], drug_test_ok: ['Yes', 'No'],
  criminal_conviction: ['No', 'Yes'], non_compete: ['No', 'Yes'],
  gender: ['Decline to self-identify', 'Male', 'Female', 'Non-binary'],
  race: ['Decline to self-identify', 'Asian', 'Black or African American', 'Hispanic or Latino', 'White', 'Two or More Races', 'American Indian or Alaska Native', 'Native Hawaiian or Other Pacific Islander'],
  hispanic_latino: ['Decline to self-identify', 'Yes', 'No'],
  veteran: ['I am not a protected veteran', 'I identify as one or more of the classifications of protected veteran', 'I don\'t wish to answer'],
  disability: ['I do not want to answer', 'No, I do not have a disability and have not had one in the past', 'Yes, I have a disability (or previously had a disability)'],
  sexual_orientation: ['Decline to self-identify', 'Heterosexual', 'Gay or Lesbian', 'Bisexual'], transgender: ['Decline to self-identify', 'No', 'Yes'],
  how_did_you_hear: ['Online job board', 'LinkedIn', 'Company website', 'Referral', 'Career fair', 'University career center'],
  salary_expectation: ['Negotiable'], start_date: ['Immediately', 'Two weeks notice', 'May 2026', 'June 2026'],
};

PAGES.answers = {
  title: 'Answers', icon: 'chat',
  async render(main) {
    const d = await api('/api/answers');
    S.answers = d.data;
    localStorage.setItem('ab-answers-reviewed', '1');
    main.innerHTML = `<div class="page">
      <div class="page-head">
        <div><h1>Standard answers</h1><p class="muted">How ApplyBot answers the questions most applications ask. Anything it can't answer, it asks you — and remembers.</p></div>
        <div class="row" style="gap:8px">
          <button class="btn ghost" data-act="answers-yaml">${icon('code')} Edit as YAML</button>
          <button class="btn primary" id="an-save" data-save>${icon('save')} Save</button>
        </div>
      </div>
      <div id="an-body"></div>
      <div class="sticky-save" id="an-sticky" hidden><span>You have unsaved changes</span><button class="btn primary sm" data-act="answers-save">${icon('save')} Save</button></div>
    </div>`;
    renderAnswers();
    $('#an-save').onclick = saveAnswers;
  },
};

function renderAnswers() {
  const data = S.answers;
  const dl = new Set();
  const field = (sec, k, v) => {
    const sug = ANSWER_SUGGEST[k];
    if (sug) dl.add(k);
    return `<label>${esc(humanize(k))}<input class="input" data-sec="${esc(sec)}" data-key="${esc(k)}" value="${esc(v ?? '')}" ${sug ? `list="dl-${esc(k)}"` : ''} placeholder="${sec === 'sensitive' ? 'Ask me' : ''}"></label>`;
  };
  const cards = ANSWER_SECTIONS.filter((s) => data[s.key] && typeof data[s.key] === 'object').map((s) => `
    <div class="card"><div class="card-head"><h3>${icon(s.icon)} ${s.title}</h3></div><div class="card-body">
      <p class="small muted" style="margin-top:0">${s.desc}</p>
      <div class="form-grid">${Object.entries(data[s.key]).map(([k, v]) => field(s.key, k, v)).join('')}</div>
    </div></div>`).join('');
  const kvCard = (key, title, desc) => `<div class="card"><div class="card-head"><h3>${icon(key === 'custom' ? 'sliders' : 'sparkles')} ${title}</h3><div class="spacer"></div>
      <button class="btn sm" data-act="kv-add" data-kv="${key}">${icon('plus')} Add</button></div>
    <div class="card-body"><p class="small muted" style="margin-top:0">${desc}</p>
      <div class="kvlist" id="kv-${key}">${Object.entries(data[key] || {}).map(([q, a]) => kvRow(q, a)).join('') || '<div class="small faint kv-empty">None yet.</div>'}</div></div></div>`;
  $('#an-body').innerHTML = `
    <div class="card card-pad">${switchHtml('an-consent', data.auto_consent !== false, 'Automatically accept consent checkboxes', '"I agree to the privacy policy", "I certify my answers are accurate", etc.')}</div>
    ${cards}
    ${kvCard('custom', 'Your own rules', 'If a form question contains the text on the left, ApplyBot answers with the text on the right.')}
    ${kvCard('learned', 'Learned answers', 'Answers you gave at prompts. They are reused for the same question next time — edit or remove them here.')}
    ${[...dl].map((k) => `<datalist id="dl-${esc(k)}">${ANSWER_SUGGEST[k].map((o) => `<option value="${esc(o)}">`).join('')}</datalist>`).join('')}`;
  $('#an-body').oninput = () => { setDirty(); $('#an-sticky').hidden = false; };
  $('#an-body').onchange = () => { setDirty(); $('#an-sticky').hidden = false; };
}
function kvRow(q, a) {
  return `<div class="kvrow"><input class="input" data-kv-q value="${esc(q)}" placeholder="Question contains…">
    <input class="input" data-kv-a value="${esc(typeof a === 'string' ? a : JSON.stringify(a))}" placeholder="Answer">
    <button class="icon-btn" data-act="kv-del" title="Remove">${icon('trash')}</button></div>`;
}
ACTIONS['kv-add'] = (el) => {
  const list = $('#kv-' + el.dataset.kv);
  list.querySelector('.kv-empty')?.remove();
  list.insertAdjacentHTML('beforeend', kvRow('', ''));
  list.lastElementChild.querySelector('input').focus();
  setDirty(); $('#an-sticky').hidden = false;
};
ACTIONS['kv-del'] = (el) => { el.closest('.kvrow').remove(); setDirty(); $('#an-sticky').hidden = false; };
ACTIONS['answers-save'] = () => saveAnswers();

async function saveAnswers() {
  const data = JSON.parse(JSON.stringify(S.answers));
  $$('#an-body input[data-sec]').forEach((i) => { data[i.dataset.sec][i.dataset.key] = i.value; });
  data.auto_consent = $('#an-consent').checked;
  for (const key of ['custom', 'learned']) {
    const out = {};
    $$(`#kv-${key} .kvrow`).forEach((r) => {
      const q = r.querySelector('[data-kv-q]').value.trim();
      if (q) out[q] = r.querySelector('[data-kv-a]').value;
    });
    data[key] = out;
  }
  try {
    await api('/api/answers', { data });
    S.answers = data;
    setDirty(false);
    $('#an-sticky').hidden = true;
    toast('Answers saved', 'ok');
  } catch (e) { fail(e); }
}

ACTIONS['answers-yaml'] = () => openYamlEditor('answers', 'answers.yaml', () => { if (S.page === 'answers') PAGES.answers.render($('#main')); });

async function openYamlEditor(name, title, after) {
  let f;
  try { f = await api('/api/file?name=' + name); } catch (e) { fail(e); return; }
  openModal({
    title, iconName: 'code', wide: true,
    body: `<p class="small muted" style="margin-top:0">Advanced: edit the raw file. It's checked for errors before saving.</p>
      <textarea class="editor mono" id="y-text" style="min-height:52vh" spellcheck="false">${esc(f.text)}</textarea>`,
    foot: `<span class="tiny faint mono clip" style="margin-right:auto" title="${esc(f.path)}">${esc(f.path)}</span>
      <button class="btn ghost" data-act="modal-close">Cancel</button><button class="btn primary" id="y-save">${icon('save')} Save</button>`,
  });
  $('#y-save').onclick = async () => {
    try {
      await api('/api/file', { name, text: $('#y-text').value });
      closeModal();
      toast(`${title} saved`, 'ok');
      loadState().catch(() => {});
      if (after) after();
    } catch (e) { fail(e); }
  };
}
