'use strict';
/* ApplyBot UI - settings page. */

const PROVIDERS = [
  { id: 'openai', n: 'OpenAI', d: 'GPT models. Fast and reliable.', models: ['gpt-4o-mini', 'gpt-4.1-mini', 'gpt-4.1', 'gpt-4o', 'gpt-5-mini', 'gpt-5'], key: true },
  { id: 'anthropic', n: 'Anthropic Claude', d: 'Excellent writing quality.', models: ['claude-sonnet-4-5', 'claude-haiku-4-5', 'claude-opus-4-1'], key: true },
  { id: 'gemini', n: 'Google Gemini', d: 'Generous free tier.', models: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash'], key: true },
  { id: 'ollama', n: 'Ollama (local)', d: 'Free, private, runs on your PC.', models: ['llama3.1', 'qwen2.5', 'mistral', 'gemma2'], base: 'http://localhost:11434' },
  { id: 'openai_compatible', n: 'OpenAI-compatible', d: 'Groq, OpenRouter, LM Studio, Together…', models: ['llama-3.3-70b-versatile'], key: true, base: 'https://api.groq.com/openai/v1' },
  { id: 'command', n: 'Command line', d: 'Any program that reads a prompt on stdin.', models: [] },
  { id: 'none', n: 'No AI', d: 'Keyword scoring and template cover letters.', models: [] },
];
const SOURCES = [
  { id: 'simplify', n: 'Simplify (GitHub lists)', d: 'Thousands of curated internship and new-grad postings.', list: 'repos', listLabel: 'Repositories', ph: 'owner/repo' },
  { id: 'greenhouse', n: 'Greenhouse', d: 'Company job boards at boards.greenhouse.io/<company>.', list: 'companies', listLabel: 'Companies', ph: 'board token, e.g. stripe' },
  { id: 'lever', n: 'Lever', d: 'Company job boards at jobs.lever.co/<company>.', list: 'companies', listLabel: 'Companies', ph: 'slug, e.g. palantir' },
  { id: 'ashby', n: 'Ashby', d: 'Company job boards at jobs.ashbyhq.com/<company>.', list: 'companies', listLabel: 'Companies', ph: 'slug, e.g. ramp' },
  { id: 'remotive', n: 'Remotive', d: 'Remote jobs (software category).' },
  { id: 'remoteok', n: 'RemoteOK', d: 'Remote tech jobs.' },
  { id: 'arbeitnow', n: 'Arbeitnow', d: 'Jobs in Europe, many remote.' },
  { id: 'jobspy', n: 'LinkedIn / Indeed / Glassdoor', d: 'Via python-jobspy. Only available when running from source with "pip install python-jobspy".', list: 'sites', listLabel: 'Sites', ph: 'indeed, linkedin, glassdoor, zip_recruiter' },
];
const JOB_TYPES = ['internship', 'full-time', 'part-time', 'contract'];

PAGES.settings = {
  title: 'Settings', icon: 'settings',
  async render(main) {
    const s = await api('/api/settings');
    S.settings = s;
    const ai = s.ai;
    const se = s.search;
    const src = se.sources || {};
    const m = s.matching;
    const a = s.apply;
    const delay = Array.isArray(a.delay_seconds) ? a.delay_seconds : [15, 45];
    main.innerHTML = `<div class="page">
      <div class="page-head">
        <div><h1>Settings</h1><p class="muted">Choose your AI, where to look for jobs, and how ApplyBot applies.</p></div>
        <div class="row" style="gap:8px">
          <button class="btn ghost" data-act="config-yaml">${icon('code')} Edit config.yaml</button>
          <button class="btn primary" id="st-save" data-save>${icon('save')} Save settings</button>
        </div>
      </div>

      <div class="card" id="sec-ai"><div class="card-head"><h3>${icon('cpu')} AI model</h3><div class="spacer"></div>
        <span id="ai-status">${S.state && S.state.ai.available ? pill('done').replace('Done', 'Connected') : ''}</span></div>
        <div class="card-body">
          <div class="provider-grid">${PROVIDERS.map((p) => `<button type="button" class="provider${p.id === ai.provider ? ' on' : ''}" data-act="pick-provider" data-p="${p.id}">
            <span class="pn">${p.n}</span><span class="pd">${p.d}</span>${p.key && s.key_status[p.id] ? '<span class="tiny" style="color:var(--green)">● key saved</span>' : ''}</button>`).join('')}</div>
          <div class="form-grid" id="ai-fields" style="margin-top:16px"></div>
          <div class="row" style="margin-top:14px">
            <button class="btn" data-act="ai-test">${icon('zap')} Test connection</button>
            <span id="ai-test-out" class="small"></span>
          </div>
          <p class="tiny muted" style="margin-bottom:0">Keys are stored only on this computer, in the <span class="mono">.env</span> file in your data folder.
            Save settings before testing.</p>
        </div></div>

      <div class="card"><div class="card-head"><h3>${icon('search')} What to look for</h3></div><div class="card-body">
        <div class="form-grid">
          <label class="full">Job title keywords <span class="faint">— a posting is kept if its title contains any of these</span>${tagInput('kw', se.keywords, 'e.g. software engineer, data analyst')}</label>
          <label>Exclude titles containing${tagInput('ex', se.exclude_keywords, 'e.g. senior, manager')}</label>
          <label>Title must contain all of <span class="faint">(optional)</span>${tagInput('req', se.required_keywords, 'e.g. intern')}</label>
          <label>Locations <span class="faint">— empty means anywhere</span>${tagInput('loc', se.locations, 'e.g. New York, Seattle, CA')}</label>
          <label>Ignore postings older than (days)<input class="input" type="number" id="st-age" min="1" max="365" value="${se.max_age_days ?? 45}"></label>
          <div class="full"><div class="small" style="font-weight:600;margin-bottom:6px">Job types <span class="faint" style="font-weight:400">— none selected means any</span></div>
            <div class="row">${JOB_TYPES.map((t) => `<label class="row small" style="gap:6px"><input type="checkbox" class="check" data-jobtype="${t}" ${(se.job_types || []).includes(t) ? 'checked' : ''}>${humanize(t)}</label>`).join('')}</div></div>
          <div class="full">${switchHtml('st-remote', se.remote_ok !== false, 'Include remote jobs', 'Remote postings pass the location filter.')}</div>
        </div></div></div>

      <div class="card"><div class="card-head"><h3>${icon('globe')} Job sources</h3></div><div class="card-body" style="padding-top:4px;padding-bottom:4px">
        ${SOURCES.map((x) => {
          const cfg = src[x.id] || {};
          return `<div class="src-row"><div class="src-top">${`<label class="switch"><input type="checkbox" data-src="${x.id}" ${cfg.enabled ? 'checked' : ''}><span class="track"></span></label>`}
            <div class="grow"><b>${x.n}</b><div class="tiny muted">${esc(x.d)}</div></div></div>
            ${x.list ? `<div class="src-body"><div class="tiny muted" style="margin-bottom:4px">${x.listLabel}</div>${tagInput('src-' + x.id, cfg[x.list] || [], x.ph)}</div>` : ''}
            ${x.id === 'jobspy' ? `<div class="src-body form-grid" style="margin-top:4px"><label class="small">Location<input class="input" id="jobspy-loc" value="${esc(cfg.location || '')}"></label>
              <label class="small">Results per site<input class="input" type="number" id="jobspy-n" value="${cfg.results_wanted ?? 30}"></label></div>` : ''}
          </div>`;
        }).join('')}
      </div></div>

      <div class="grid g-2">
        <div class="card"><div class="card-head"><h3>${icon('target')} Matching</h3></div><div class="card-body">
          <label class="small" style="font-weight:600">Minimum match score to apply: <b id="st-min-v">${m.min_score}</b></label>
          <input type="range" class="range" id="st-min" min="0" max="100" step="5" value="${m.min_score}" style="width:100%">
          <div class="row tiny muted"><span>Apply broadly</span><div class="spacer"></div><span>Only perfect fits</span></div>
          <div style="margin-top:14px">${switchHtml('st-useai', m.use_ai !== false, 'Use AI to score jobs', 'Off = fast keyword matching (no AI cost).')}</div>
        </div></div>
        <div class="card"><div class="card-head"><h3>${icon('send')} Applying</h3></div><div class="card-body">
          <div class="form-grid">
            <label>Applications per run<input class="input" type="number" id="st-run" min="1" max="500" value="${a.max_per_run}"></label>
            <label>Applications per day<input class="input" type="number" id="st-day" min="1" max="1000" value="${a.max_per_day}"></label>
            <label>Wait between applications (s)<div class="row" style="flex-wrap:nowrap"><input class="input" type="number" id="st-d0" min="0" value="${delay[0]}"><span class="faint">to</span><input class="input" type="number" id="st-d1" min="0" value="${delay[1]}"></div></label>
            <label>Résumé formats<div class="row" style="height:38px">${['pdf', 'docx'].map((f) => `<label class="row small" style="gap:6px"><input type="checkbox" class="check" data-fmt="${f}" ${(a.resume_formats || []).includes(f) ? 'checked' : ''}>${f.toUpperCase()}</label>`).join('')}</div></label>
          </div>
          <div style="margin-top:12px;display:grid;gap:10px">
            ${switchHtml('st-cover', a.cover_letter !== false, 'Write a cover letter for each job')}
            ${switchHtml('st-headless', a.headless, 'Hide the browser window by default', 'Review mode always shows it.')}
          </div>
        </div></div>
      </div>

      <div class="card"><div class="card-head"><h3>${icon('hand')} Default apply mode</h3></div><div class="card-body">${modeCards(a.mode || 'review', 'defmode')}</div></div>

      <div class="card"><div class="card-head"><h3>${icon('folder')} System</h3></div><div class="card-body">
        <div class="list">
          <div class="li">${icon('folder')}<div class="grow"><div class="t1">Data folder</div><div class="t2 mono clip" title="${esc(s.data_dir)}">${esc(s.data_dir)}</div></div>
            <button class="btn sm" data-act="open-data">Open</button></div>
          <div class="li">${icon('globe')}<div class="grow"><div class="t1">Form-filling browser (Chromium)</div><div class="t2">${s.browser_installed ? 'Installed' : 'Not installed — needed to apply'}</div></div>
            <button class="btn sm ${s.browser_installed ? '' : 'primary'}" data-act="install-browser">${s.browser_installed ? 'Reinstall' : 'Install'}</button></div>
          <div class="li">${icon('sparkles')}<div class="grow"><div class="t1">Re-score all jobs</div><div class="t2">After changing your profile or keywords.</div></div>
            <button class="btn sm" data-act="rescore">Re-score</button></div>
        </div>
      </div></div>
      <div class="sticky-save" id="st-sticky" hidden><span>You have unsaved changes</span><button class="btn primary sm" data-act="settings-save">${icon('save')} Save settings</button></div>
    </div>`;
    S.aiDraft = { provider: ai.provider, model: ai.model || '', base_url: ai.base_url || '', command: ai.command || '', api_key: '' };
    renderAiFields();
    $('#st-min').oninput = (e) => { $('#st-min-v').textContent = e.target.value; };
    const mark = () => { setDirty(); $('#st-sticky').hidden = false; };
    main.addEventListener('input', (e) => { if (e.target.closest('.page') && !e.target.closest('.tags')) mark(); });
    main.addEventListener('change', mark);
    main.addEventListener('modechange', mark);
    $('#st-save').onclick = saveSettings;
  },
};

function renderAiFields() {
  const d = S.aiDraft;
  const p = PROVIDERS.find((x) => x.id === d.provider) || PROVIDERS[0];
  const s = S.settings;
  const keySaved = s.key_status[p.id];
  const f = [];
  if (p.models.length || p.id === 'openai_compatible') {
    f.push(`<label>Model<input class="input" id="ai-model" list="ai-models" value="${esc(d.model)}" placeholder="${esc(p.models[0] || '')}">
      <datalist id="ai-models">${p.models.map((x) => `<option value="${esc(x)}">`).join('')}</datalist></label>`);
  }
  if (p.key) {
    f.push(`<label>API key ${keySaved ? `<span class="tiny" style="color:var(--green)">saved${s.ai.provider === p.id && s.ai.key_hint ? ' (' + esc(s.ai.key_hint) + ')' : ''}</span>` : ''}
      <input class="input" id="ai-key" type="password" autocomplete="off" value="${esc(d.api_key)}" placeholder="${keySaved ? 'Leave empty to keep the saved key' : 'Paste your API key'}"></label>`);
  }
  if (p.base) f.push(`<label class="${p.key ? 'full' : ''}">Server URL<input class="input" id="ai-base" value="${esc(d.base_url)}" placeholder="${esc(p.base)}"></label>`);
  if (p.id === 'command') f.push(`<label class="full">Command<input class="input mono" id="ai-cmd" value="${esc(d.command)}" placeholder="ollama run llama3.1"></label>`);
  const help = {
    openai: 'Get a key at <a href="#" data-act="open-url" data-url="https://platform.openai.com/api-keys">platform.openai.com/api-keys</a>.',
    anthropic: 'Get a key at <a href="#" data-act="open-url" data-url="https://console.anthropic.com/settings/keys">console.anthropic.com</a>.',
    gemini: 'Get a free key at <a href="#" data-act="open-url" data-url="https://aistudio.google.com/apikey">aistudio.google.com/apikey</a>.',
    ollama: 'Install from <a href="#" data-act="open-url" data-url="https://ollama.com/download">ollama.com</a>, then run <span class="mono">ollama pull llama3.1</span>.',
    openai_compatible: 'Any server that speaks the OpenAI chat API. For Groq use https://api.groq.com/openai/v1.',
    command: 'The prompt is sent on standard input; the reply is read from standard output.',
    none: 'Without AI, jobs are scored by keyword overlap, résumés are tailored by keyword relevance, and cover letters use a template. Everything still works.',
  }[p.id];
  $('#ai-fields').innerHTML = f.join('') + `<div class="full tiny muted">${help}</div>`;
  const bind = (sel, k) => { const el = $(sel); if (el) el.oninput = () => { d[k] = el.value; }; };
  bind('#ai-model', 'model'); bind('#ai-key', 'api_key'); bind('#ai-base', 'base_url'); bind('#ai-cmd', 'command');
}

ACTIONS['pick-provider'] = (el) => {
  const d = S.aiDraft;
  const prev = PROVIDERS.find((x) => x.id === d.provider);
  const next = PROVIDERS.find((x) => x.id === el.dataset.p);
  $$('.provider').forEach((b) => b.classList.toggle('on', b === el));
  if (!d.model || (prev && prev.models.includes(d.model)) || d.provider !== next.id) {
    d.model = next.id === S.settings.ai.provider ? (S.settings.ai.model || next.models[0] || '') : (next.models[0] || '');
  }
  if (next.id !== d.provider) {
    d.base_url = next.id === S.settings.ai.provider ? S.settings.ai.base_url : '';
    d.api_key = '';
  }
  d.provider = next.id;
  renderAiFields();
  setDirty();
  $('#st-sticky').hidden = false;
};

ACTIONS['ai-test'] = async () => {
  const out = $('#ai-test-out');
  if (S.dirty) {
    const ok = await saveSettings(true);
    if (!ok) return;
  }
  out.innerHTML = '<span class="spin"></span> Asking the model…';
  try {
    const r = await api('/api/ai/test', {});
    out.innerHTML = r.ok ? `<span style="color:var(--green)">${icon('checkCircle', 'sm')} Connected — ${esc(r.provider)} ${esc(r.model || '')} replied in ${r.seconds}s</span>`
      : `<span style="color:var(--red)">${icon('alert', 'sm')} ${esc(r.error)}</span>`;
  } catch (e) { out.innerHTML = `<span style="color:var(--red)">${esc(e.message)}</span>`; }
};
ACTIONS['settings-save'] = () => saveSettings();
ACTIONS['config-yaml'] = () => {
  if (S.dirty && !confirm('Discard unsaved changes on this page and open the raw config?')) return;
  setDirty(false);
  openYamlEditor('config', 'config.yaml', () => { if (S.page === 'settings') PAGES.settings.render($('#main')); });
};

async function saveSettings(quiet = false) {
  const num = (id, dflt) => { const v = Number($(id).value); return Number.isFinite(v) && $(id).value !== '' ? v : dflt; };
  const d = S.aiDraft;
  const sources = {};
  for (const x of SOURCES) {
    const o = { enabled: $(`[data-src="${x.id}"]`).checked };
    if (x.list) o[x.list] = S.tags['src-' + x.id];
    if (x.id === 'jobspy') { o.location = $('#jobspy-loc').value.trim(); o.results_wanted = num('#jobspy-n', 30); }
    sources[x.id] = o;
  }
  const jobTypes = $$('[data-jobtype]').filter((c) => c.checked).map((c) => c.dataset.jobtype);
  const fmts = $$('[data-fmt]').filter((c) => c.checked).map((c) => c.dataset.fmt);
  const d0 = num('#st-d0', 15), d1 = num('#st-d1', 45);
  const body = {
    ai: { provider: d.provider, model: d.model, base_url: d.base_url, command: d.command, api_key: d.api_key },
    search: {
      keywords: S.tags.kw, exclude_keywords: S.tags.ex, required_keywords: S.tags.req, locations: S.tags.loc,
      max_age_days: num('#st-age', 45), job_types: jobTypes, remote_ok: $('#st-remote').checked, sources,
    },
    matching: { min_score: Number($('#st-min').value), use_ai: $('#st-useai').checked },
    apply: {
      max_per_run: num('#st-run', 10), max_per_day: num('#st-day', 25), delay_seconds: [Math.min(d0, d1), Math.max(d0, d1)],
      resume_formats: fmts.length ? fmts : ['pdf'], cover_letter: $('#st-cover').checked, headless: $('#st-headless').checked,
      mode: pickedMode($('#main'), 'defmode') || 'review',
    },
  };
  if (!body.search.keywords.length && !confirm('No title keywords are set, so every posting will be kept. Continue?')) return false;
  try {
    await api('/api/settings', body);
    setDirty(false);
    $('#st-sticky').hidden = true;
    if (!quiet) toast('Settings saved', 'ok');
    const keyTyped = !!d.api_key;
    await loadState();
    S.settings = await api('/api/settings');
    if (keyTyped) { d.api_key = ''; renderAiFields(); }
    $('#ai-status').innerHTML = S.state.ai.available ? pill('done').replace('Done', 'Connected') : '';
    return true;
  } catch (e) { fail(e); return false; }
}
