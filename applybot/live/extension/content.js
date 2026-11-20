// ApplyBot Live content script: reads the application form on this page, asks the local ApplyBot what to
// fill, fills it, and applies live edits. It never reads or fills password fields - your browser's own
// password manager handles sign-ins.
(() => {
  if (window.__applybotLive) return;
  window.__applybotLive = true;

  const api = typeof browser !== "undefined" ? browser : (typeof chrome !== "undefined" ? chrome : null);
  const send = (msg) => window.__applybotSend ? window.__applybotSend(msg) : api.runtime.sendMessage(msg);

  const CONFIRM_RE = /thank(s| you) for (applying|your (application|interest|submission))|application (has been |was )?(received|submitted)|we('ve| have) received your|successfully submitted|submission (received|successful)|your application is (complete|in)/i;
  const SUBMIT_RE = /^\s*(submit( your| my)?( application)?|send( application)?|complete( application)?|apply( now)?|finish)\s*$/i;
  const fields = new Map();   // key -> { kind, els: [elements], label }
  let seq = 0, filled = {}, unresolved = [], job = null, lastState = "", offline = false, panel = null;

  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) && getComputedStyle(el).visibility !== "hidden";

  function labelFor(el) {
    const byId = el.id && document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
    if (byId) return clean(byId.innerText);
    const ref = el.getAttribute("aria-labelledby");
    if (ref) {
      const t = clean(ref.split(/\s+/).map((id) => (document.getElementById(id) || {}).innerText || "").join(" "));
      if (t) return t;
    }
    if (el.getAttribute("aria-label")) return clean(el.getAttribute("aria-label"));
    const wrap = el.closest("label");
    if (wrap) return clean(wrap.innerText);
    return clean(el.placeholder || "");
  }

  function groupLabel(el) {
    const set = el.closest("fieldset");
    const legend = set && set.querySelector("legend");
    if (legend) return clean(legend.innerText);
    const group = el.closest('[role="radiogroup"],[role="group"]');
    if (group) {
      const ref = group.getAttribute("aria-labelledby");
      const t = ref ? clean((document.getElementById(ref) || {}).innerText) : clean(group.getAttribute("aria-label"));
      if (t) return t;
    }
    return "";
  }

  const isRequired = (el, label) => el.required || el.getAttribute("aria-required") === "true" || /\*\s*$/.test(label);

  function keyFor(el) {
    if (!el.dataset.applybotKey) el.dataset.applybotKey = "f" + (++seq);
    return el.dataset.applybotKey;
  }

  function scan() {
    fields.clear();
    const out = [], groups = new Map();
    for (const el of document.querySelectorAll("input, textarea, select")) {
      const type = (el.getAttribute("type") || el.tagName).toLowerCase();
      if (type === "password" || type === "hidden" || type === "submit" || type === "button" || type === "image") continue;
      if (el.disabled || (type !== "file" && !visible(el))) continue;
      if (el.getAttribute("aria-hidden") === "true" && type !== "file") continue;   // e.g. react-select's shadow input
      if (type === "radio" || type === "checkbox") {
        const label = groupLabel(el);
        if (type === "checkbox" && !label) {   // a single stand-alone checkbox
          const key = keyFor(el), l = labelFor(el);
          fields.set(key, { kind: "checkbox", els: [el], label: l });
          out.push({ key, kind: "checkbox", label: l, required: isRequired(el, l), options: ["Yes", "No"], value: el.checked ? "Yes" : "" });
          continue;
        }
        const gid = type + ":" + (el.name || label);
        if (!groups.has(gid)) {
          const key = keyFor(el);
          const g = { key, kind: type === "radio" ? "radio" : "checkbox_group", label, required: false, options: [], value: "", name: el.name || "" };
          groups.set(gid, g);
          fields.set(key, { kind: g.kind, els: [], label });
          out.push(g);
        }
        const g = groups.get(gid), opt = labelFor(el);
        g.options.push(opt);
        g.required = g.required || isRequired(el, label);
        if (el.checked) g.value = g.value ? g.value + ", " + opt : opt;
        fields.get(g.key).els.push(el);
        continue;
      }
      const key = keyFor(el);
      // an upload button is usually labelled "Attach"; the group around it says what the file is
      const label = type === "file" ? clean([groupLabel(el), el.id, el.name].join(" ")) || labelFor(el) : labelFor(el);
      let kind = type === "select" ? "select" : type === "textarea" ? "textarea" : type === "file" ? "file"
        : ["email", "tel", "url", "number", "date"].includes(type) ? type : "text";
      if (kind === "text" && (el.getAttribute("role") === "combobox" || el.getAttribute("aria-autocomplete"))) kind = "combobox";
      const f = { key, kind, label, required: isRequired(el, label), name: el.name || "", placeholder: el.placeholder || "", value: "" };
      if (kind === "select") {
        f.options = [...el.options].map((o) => clean(o.text)).filter(Boolean);
        f.value = el.selectedIndex > 0 || (el.value && el.selectedIndex === 0 && el.options[0].value) ? clean(el.options[el.selectedIndex].text) : "";
      } else if (kind === "file") {
        f.value = el.files && el.files.length ? el.files[0].name : "";
      } else if (kind === "combobox") {
        f.value = comboValue(el);
      } else {
        f.value = el.value || "";
      }
      fields.set(key, { kind, els: [el], label });
      out.push(f);
    }
    return out;
  }

  function fire(el, names) {
    for (const n of names) el.dispatchEvent(new Event(n, { bubbles: true }));
  }

  function typeInto(el, value) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    el.focus();
    setter.call(el, value);          // React and friends watch the native setter, not el.value
    fire(el, ["input", "change"]);
  }

  const norm = (s) => clean(s).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  function bestOption(options, value) {
    const v = norm(value);
    return options.find((o) => norm(o.text) === v) || options.find((o) => norm(o.text).startsWith(v))
      || options.find((o) => norm(o.text).includes(v) || (norm(o.text) && v.includes(norm(o.text))));
  }

  function comboShell(el) {   // the widget around a react-select search box: its control plus the chosen value
    const control = el.closest('[class*="__control"], [class*="-control"]');
    return el.closest('[class*="select-shell"]') || (control && control.parentElement) || el.parentElement;
  }

  function comboValue(el) {
    const shell = comboShell(el);
    const picked = shell && [...shell.querySelectorAll('[class*="single-value"], [class*="singleValue"], [class*="multi-value__label"], [class*="multiValueLabel"]')];
    if (picked && picked.length) return clean(picked.map((n) => n.innerText).join(", "));
    const isReactSelect = shell && shell.querySelector('[class*="__control"], [class*="-control"]');
    return isReactSelect ? "" : (el.value || "");   // text left in a react-select search box is not a selection
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function comboOptions(el) {
    const id = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
    const box = id && document.getElementById(id);
    const found = box ? [...box.querySelectorAll('[role="option"]')] : [...document.querySelectorAll('[role="option"]')].filter(visible);
    return found.map((o) => ({ el: o, text: o.innerText }));
  }

  async function openCombo(el) {
    if (el.getAttribute("aria-expanded") === "true") return;
    const control = el.closest('[class*="__control"], [class*="-control"]') || el;
    const mouse = (t) => control.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, button: 0, view: window }));
    if (document.activeElement === el) el.blur();
    control.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, button: 0 }));
    mouse("mousedown");
    el.focus();
    mouse("mouseup");
    mouse("click");
    for (let i = 0; i < 10 && el.getAttribute("aria-expanded") !== "true"; i++) await sleep(100);
  }

  async function pickCombobox(el, value) {
    if (comboValue(el) && norm(comboValue(el)) === norm(value)) return true;
    await openCombo(el);
    let hit = bestOption(comboOptions(el), value);
    if (!hit) {                       // lists that load as you type (schools, cities)
      typeInto(el, value);
      for (let i = 0; i < 20 && !hit; i++) {
        await sleep(150);
        hit = bestOption(comboOptions(el), value);
      }
    }
    if (!hit) {
      if (el.value) typeInto(el, "");
      el.blur();
      return false;
    }
    hit.el.click();
    await sleep(150);
    return true;
  }

  async function setValue(key, value) {
    const f = fields.get(key);
    if (!f || f.kind === "password" || f.kind === "file") return false;
    const el = f.els[0];
    if (f.kind === "select") {
      const hit = bestOption([...el.options].map((o) => ({ el: o, text: o.text })), value);
      if (!hit) return false;
      el.value = hit.el.value;
      fire(el, ["input", "change"]);
      return true;
    }
    if (f.kind === "radio" || f.kind === "checkbox_group") {
      const wanted = f.kind === "radio" ? [value] : String(value).split(/\s*,\s*/);
      let any = false;
      for (const w of wanted) {
        const hit = bestOption(f.els.map((e) => ({ el: e, text: labelFor(e) })), w);
        if (hit && !hit.el.checked) hit.el.click();
        any = any || !!hit;
      }
      return any;
    }
    if (f.kind === "checkbox") {
      const want = /^(yes|true|1|on)$/i.test(String(value));
      if (el.checked !== want) el.click();
      return true;
    }
    if (f.kind === "combobox") return pickCombobox(el, value);
    typeInto(el, value);
    fire(el, ["blur"]);
    return true;
  }

  async function attach(key, path) {
    const f = fields.get(key);
    if (!f || f.kind !== "file") return false;
    const got = await send({ type: "file", path });
    if (!got || !got.ok) return false;
    const file = new File([new Uint8Array(got.bytes)], got.name, { type: "application/pdf" });
    const dt = new DataTransfer();
    dt.items.add(file);
    f.els[0].files = dt.files;
    fire(f.els[0], ["input", "change"]);
    return true;
  }

  function mark() {
    for (const [key, f] of fields) {
      const need = unresolved.includes(key);
      for (const el of f.els) el.style.outline = need ? "2px solid #e0a800" : (key in filled ? "2px solid #2f9e44" : "");
    }
  }

  function draw(note) {
    if (window.top !== window && !fields.size) return;
    if (!panel) {
      panel = document.createElement("div");
      panel.id = "applybot-live-panel";
      panel.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:320px;max-height:50vh;overflow:auto;" +
        "background:#16181d;color:#f1f3f5;font:13px/1.45 system-ui,sans-serif;padding:12px 14px;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.35)";
      document.documentElement.appendChild(panel);
    }
    panel.textContent = "";
    const head = document.createElement("div");
    head.style.cssText = "font-weight:600;margin-bottom:4px";
    head.textContent = offline ? "ApplyBot: not running" : "ApplyBot" + (job ? " · " + job.company : "");
    panel.appendChild(head);
    const line = document.createElement("div");
    line.textContent = offline ? "Open the Claude desktop app (or run ApplyBot) and reload this page."
      : note || (Object.keys(filled).length + " filled · " + unresolved.length + " need you");
    panel.appendChild(line);
    for (const key of unresolved.slice(0, 12)) {
      const f = fields.get(key);
      if (!f) continue;
      const a = document.createElement("a");
      a.textContent = "• " + (f.label || "unlabelled field").slice(0, 70);
      a.href = "#";
      a.style.cssText = "display:block;color:#ffd43b;text-decoration:none;margin-top:3px";
      a.addEventListener("click", (e) => { e.preventDefault(); f.els[0].scrollIntoView({ block: "center", behavior: "smooth" }); f.els[0].focus(); });
      panel.appendChild(a);
    }
  }

  async function run() {
    const list = scan();
    if (!list.length) return;
    const resp = await send({ type: "page", data: { url: location.href, title: document.title, fields: list } });
    offline = !resp || !!resp.offline;
    if (offline) { draw(); return; }
    job = resp.job;
    filled = {};
    for (const item of resp.fill || []) {
      const cur = list.find((f) => f.key === item.key);
      if (cur && cur.value && !item.file) { filled[item.key] = cur.value; continue; }   // never overwrite what's there
      const ok = item.file ? await attach(item.key, item.file) : await setValue(item.key, item.value);
      if (ok) filled[item.key] = item.value || item.filename;
    }
    await report();
    window.__applybotReady = true;
    autoSubmit = !!resp.auto_submit;
    maybeAutoSubmit();
  }

  // ---- auto-submit: only when nothing required is empty and no bot check is on the page ----
  let autoSubmit = false, countdown = null, cancelled = false;
  const CAPTCHA_SEL = 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], iframe[title*="captcha" i], .g-recaptcha, .h-captcha, .cf-turnstile';

  function submitButton() {
    return [...document.querySelectorAll('button, input[type="submit"]')]
      .find((b) => visible(b) && !b.disabled && SUBMIT_RE.test(b.innerText || b.value || ""));
  }

  function maybeAutoSubmit() {
    if (!autoSubmit || cancelled || countdown || done) return;
    const btn = submitButton();
    if (!btn || unresolved.length || document.querySelector(CAPTCHA_SEL)) return;
    let left = 5;
    const tick = () => {
      if (cancelled || unresolved.length) { clearInterval(countdown); countdown = null; draw(); return; }
      if (left <= 0) {
        clearInterval(countdown); countdown = null;
        draw("Submitting…");
        btn.click();
        return;
      }
      draw("All filled - submitting in " + left + "s");
      const stop = document.createElement("button");
      stop.textContent = "Cancel auto-submit";
      stop.style.cssText = "margin-top:6px;padding:4px 10px;border-radius:6px;border:0;background:#e03131;color:#fff;cursor:pointer";
      stop.addEventListener("click", () => { cancelled = true; });
      panel.appendChild(stop);
      left -= 1;
    };
    tick();
    countdown = setInterval(tick, 1000);
  }

  async function report() {
    const list = scan();
    unresolved = list.filter((f) => f.required && !f.value).map((f) => f.key);
    mark();
    draw();
    const snap = JSON.stringify(list.map((f) => [f.key, f.value]));
    if (snap !== lastState) {
      lastState = snap;
      await send({ type: "state", data: { fields: list.map((f) => ({ key: f.key, value: f.value })) } });
    }
    return list;
  }

  async function poll() {
    if (CONFIRM_RE.test(document.body ? document.body.innerText.slice(0, 6000) : "")) return confirmed();
    if (!fields.size || offline) return;
    const got = await send({ type: "commands" });
    for (const c of (got && got.commands) || []) {
      if (await setValue(c.key, c.value)) filled[c.key] = c.value;
    }
    await report();
    maybeAutoSubmit();
  }

  let done = false;
  async function confirmed() {
    if (done) return;
    done = true;
    const got = await send({ type: "confirmed", data: { url: location.href } });
    if (got && got.next) {
      draw("Applied ✓ - opening the next job…");
      setTimeout(() => { window.top.location.href = got.next; }, 1200);
    } else if (got && !got.offline) {
      draw(got.applied ? "Applied ✓ - that was the last one in the queue." : "Applied ✓");
    }
  }

  function onSubmit() {
    const list = scan();
    send({ type: "submitted", data: { url: location.href, answers: list.filter((f) => f.value && f.kind !== "file")
      .map((f) => ({ key: f.key, label: f.label, kind: f.kind, value: f.value })) } });
  }
  document.addEventListener("submit", onSubmit, true);
  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest('button, input[type="submit"], [role="button"]');
    if (b && SUBMIT_RE.test(b.innerText || b.value || "")) onSubmit();
  }, true);

  window.__applybotRun = run;
  window.__applybotPoll = poll;
  run();
  setInterval(poll, 2000);
  const count = () => document.querySelectorAll("input, textarea, select").length;
  let seen = count(), last = 0;   // forms that load late or add questions as you answer
  new MutationObserver(() => {
    if (done || Date.now() - last < 1500) return;
    last = Date.now();
    setTimeout(() => { if (count() !== seen) { seen = count(); run(); } }, 800);
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
