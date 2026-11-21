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

  // Many ATSs (Ashby, Lever, Workable) wrap each question in an "entry" whose title is the real question;
  // the input itself only carries a placeholder like "Start typing...".
  const ENTRY_SEL = '.ashby-application-form-field-entry, [class*="fieldEntry"], [class*="field-entry"], .application-question, li.application-field, [data-ui="field"]';
  const PLACEHOLDERISH = /^(start typing|type here|select|choose|search|please select)\b|^\W*$/i;
  function entryOf(el) { return el.closest(ENTRY_SEL); }
  function entryTitleEl(el) {
    const entry = entryOf(el);
    if (!entry) return null;
    return entry.querySelector('.ashby-application-form-question-title, [class*="question-title"], [class*="questionTitle"], legend, .application-label, label');
  }
  function entryTitle(el) {
    const t = entryTitleEl(el);
    return t && !t.contains(el) ? clean(t.innerText) : "";
  }
  function entryRequired(el) {
    const t = entryTitleEl(el);
    return !!t && (/required/i.test(t.className || "") || /\*\s*$/.test(t.innerText || ""));
  }

  function labelFor(el) {
    const own = ownLabel(el);
    return own && !PLACEHOLDERISH.test(own) ? own : (entryTitle(el) || own);
  }

  function ownLabel(el) {
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
    return entryTitle(el);
  }

  const isRequired = (el, label) => el.required || el.getAttribute("aria-required") === "true" || /\*\s*$/.test(label) || entryRequired(el);
  const optionLabel = (el) => ownLabel(el) || clean(el.value);

  function keyFor(el) {
    if (!el.dataset.applybotKey) el.dataset.applybotKey = "f" + (++seq);
    return el.dataset.applybotKey;
  }

  function scan() {
    fields.clear();
    const out = [], groups = new Map();
    for (const box of document.querySelectorAll('[class*="input-yesno"], [class*="_yesno_"]')) {
      const buttons = [...box.querySelectorAll("button")].filter(visible);
      if (buttons.length < 2) continue;
      const key = keyFor(box), label = entryTitle(box);
      const pressed = buttons.find((b) => b.getAttribute("aria-pressed") === "true");
      fields.set(key, { kind: "yesno", els: buttons, label });
      out.push({ key, kind: "radio", label, required: entryRequired(box), options: buttons.map((b) => clean(b.innerText)),
                 value: pressed ? clean(pressed.innerText) : "" });
    }
    for (const el of document.querySelectorAll("input, textarea, select")) {
      const type = (el.getAttribute("type") || el.tagName).toLowerCase();
      if (el.closest('[class*="input-yesno"], [class*="_yesno_"]')) continue;
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
        const g = groups.get(gid), opt = optionLabel(el);
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
        f.value = el.files && el.files.length ? el.files[0].name : uploadedName(el) || (filled[key] ? String(filled[key]) : "");
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
  const US_STATES = { AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado",
    CT: "Connecticut", DE: "Delaware", DC: "District of Columbia", FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho",
    IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland",
    MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska",
    NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York", NC: "North Carolina",
    ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island",
    SC: "South Carolina", SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia",
    WA: "Washington", WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming" };

  const DECLINE_RE = /decline|don.?t (wish|want)|do not (wish|want)|prefer not|rather not|choose not/i;
  function bestOption(options, value) {
    // "WA" in your answers, "Washington" in their list (or the other way round)
    const full = US_STATES[String(value || "").trim().toUpperCase()];
    if (full) return bestOption(options, full) || matchOption(options, value);
    // every form words "I'd rather not say" differently: your saved answer means the same thing
    if (DECLINE_RE.test(value || "")) return options.find((o) => DECLINE_RE.test(o.text)) || matchOption(options, value);
    // "Black/African American" vs "Black or African American"
    return matchOption(options, value) || (/\//.test(value || "") ? matchOption(options, value.replace(/\s*\/\s*/g, " or ")) : null);
  }

  function matchOption(options, value) {
    const v = norm(value);
    if (v.length <= 2) return options.find((o) => norm(o.text) === v);   // never let "WA" match "Hawaii"
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
        const hit = bestOption(f.els.map((e) => ({ el: e, text: optionLabel(e) })), w);
        if (hit && !hit.el.checked) hit.el.click();
        any = any || !!hit;
      }
      return any;
    }
    if (f.kind === "yesno") {
      const hit = bestOption(f.els.map((b) => ({ el: b, text: b.innerText })), value);
      if (!hit) return false;
      if (hit.el.getAttribute("aria-pressed") !== "true") hit.el.click();
      return true;
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

  // Greenhouse / Lever upload the file straight away and clear the <input>; the name then shows next to it.
  function uploadedName(el) {
    let box = el.parentElement;
    for (let i = 0; box && i < 4; i++, box = box.parentElement) {
      const m = (box.innerText || "").match(/[^\s\/\\]+\.(pdf|docx?|rtf|txt|odt)\b/i);
      if (m) return m[0];
    }
    return "";
  }

  async function attach(key, path) {
    const f = fields.get(key);
    if (!f || f.kind !== "file") return false;
    const got = await send({ type: "file", path });
    if (!got || !got.ok) return false;
    const el = f.els[0], type = /\.docx?$/i.test(got.name) ? "application/msword" : "application/pdf";
    const W = window.wrappedJSObject;
    if (W && typeof cloneInto === "function") {
      // Firefox: a File made in the extension's own world is unreadable to the page's upload code, so build the
      // File, the DataTransfer and the events in the page's world.
      const bytes = cloneInto(new Uint8Array(got.bytes), window);
      const file = new W.File(cloneInto([bytes], window), got.name, cloneInto({ type }, window));
      const dt = new W.DataTransfer();
      dt.items.add(file);
      el.wrappedJSObject.files = dt.files;
      for (const n of ["input", "change"]) el.wrappedJSObject.dispatchEvent(new W.Event(n, cloneInto({ bubbles: true }, window)));
    } else {
      const dt = new DataTransfer();
      dt.items.add(new File([new Uint8Array(got.bytes)], got.name, { type }));
      el.files = dt.files;
      fire(el, ["input", "change"]);
    }
    return true;
  }

  function mark() {
    for (const [key, f] of fields) {
      const need = unresolved.includes(key);
      for (const el of f.els) el.style.outline = need ? "2px solid #e0a800" : (key in filled ? "2px solid #2f9e44" : "");
    }
  }

  // ---- the floating panel: shadow DOM so the site's CSS can't touch it ----
  const PANEL_CSS = `
    :host { all: initial; }
    .card { position: fixed; right: 18px; bottom: 18px; z-index: 2147483647; width: 300px; max-height: 60vh;
      display: flex; flex-direction: column; overflow: hidden; border-radius: 14px;
      background: rgba(18, 20, 26, .92); backdrop-filter: blur(14px) saturate(1.4); -webkit-backdrop-filter: blur(14px);
      color: #e9ecef; font: 13px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      border: 1px solid rgba(255,255,255,.08); box-shadow: 0 18px 50px rgba(0,0,0,.45);
      animation: rise .45s cubic-bezier(.2,.9,.25,1.15) both; transition: transform .25s ease, opacity .25s ease; }
    .card.min { transform: translateY(calc(100% - 46px)); }
    .card.top { bottom: auto; top: 18px; } .card.top.min { transform: translateY(calc(-100% + 46px)); }
    .card.left { right: auto; left: 18px; }
    @keyframes rise { from { transform: translateY(24px) scale(.96); opacity: 0 } to { transform: none; opacity: 1 } }
    .head { display: flex; align-items: center; gap: 9px; padding: 12px 14px 10px; cursor: pointer; user-select: none; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #51cf66; flex: none; position: relative; }
    .dot::after { content: ""; position: absolute; inset: -4px; border-radius: 50%; background: inherit; opacity: .5;
      animation: ping 1.8s cubic-bezier(0,0,.2,1) infinite; }
    .dot.warn { background: #fcc419 } .dot.off { background: #868e96 } .dot.off::after { display: none }
    @keyframes ping { 75%, 100% { transform: scale(2.2); opacity: 0 } }
    .title { font-weight: 650; letter-spacing: .1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1 }
    .brand { font-size: 10.5px; text-transform: uppercase; letter-spacing: 1.2px; color: #748ffc; font-weight: 700 }
    .chev { color: #868e96; transition: transform .25s ease } .min .chev { transform: rotate(180deg) }
    .body { padding: 0 14px 14px; overflow: auto }
    .bar { height: 6px; border-radius: 99px; background: rgba(255,255,255,.08); overflow: hidden; margin: 2px 0 8px }
    .fill { height: 100%; border-radius: inherit; background: linear-gradient(90deg, #4c6ef5, #51cf66);
      background-size: 200% 100%; animation: shimmer 2.4s linear infinite; transition: width .6s cubic-bezier(.2,.8,.2,1) }
    @keyframes shimmer { to { background-position: -200% 0 } }
    .stats { display: flex; justify-content: space-between; color: #adb5bd; font-size: 12px; margin-bottom: 8px }
    .stats b { color: #f8f9fa; font-variant-numeric: tabular-nums }
    .note { padding: 8px 10px; border-radius: 9px; background: rgba(76,110,245,.14); color: #dbe4ff; margin-bottom: 8px;
      animation: fadein .3s ease both }
    .note.ok { background: rgba(81,207,102,.16); color: #d3f9d8 } .note.bad { background: rgba(250,82,82,.16); color: #ffe3e3 }
    .need { display: flex; gap: 8px; align-items: flex-start; width: 100%; text-align: left; border: 0; cursor: pointer;
      background: rgba(252,196,25,.08); color: #ffe8a1; padding: 7px 9px; border-radius: 8px; margin-top: 5px;
      font: inherit; transition: background .15s ease, transform .15s ease; animation: slidein .35s ease both }
    .need:hover { background: rgba(252,196,25,.18); transform: translateX(-2px) }
    .need::before { content: "→"; color: #fcc419 }
    @keyframes slidein { from { opacity: 0; transform: translateX(12px) } to { opacity: 1; transform: none } }
    @keyframes fadein { from { opacity: 0 } to { opacity: 1 } }
    .ring { display: flex; align-items: center; gap: 10px; margin-top: 4px }
    .ring svg { width: 34px; height: 34px; transform: rotate(-90deg) }
    .ring circle { fill: none; stroke-width: 4 } .ring .bg { stroke: rgba(255,255,255,.1) }
    .ring .fg { stroke: #51cf66; stroke-linecap: round; transition: stroke-dashoffset 1s linear }
    .cancel { margin-left: auto; border: 0; border-radius: 8px; padding: 6px 10px; cursor: pointer; font: inherit;
      font-weight: 600; background: #fa5252; color: #fff; transition: filter .15s } .cancel:hover { filter: brightness(1.1) }
    .check { display: inline-block; width: 22px; height: 22px; border-radius: 50%; background: #51cf66; color: #0b1e0f;
      text-align: center; line-height: 22px; font-weight: 800; animation: pop .5s cubic-bezier(.2,1.6,.4,1) both }
    @keyframes pop { from { transform: scale(0) } to { transform: scale(1) } }
  `;
  let shadow = null, card = null, minimized = false, countdownLeft = 0, lastNeed = "";

  function ensurePanel() {
    if (card && card.isConnected) return;
    panel = document.createElement("div");
    panel.id = "applybot-live-panel";
    shadow = panel.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = PANEL_CSS;
    card = document.createElement("div");
    card.className = "card";
    shadow.append(style, card);
    document.documentElement.appendChild(panel);
  }

  // Never sit on top of the Submit button (or whatever the page has under the panel's corner).
  const CORNERS = [[], ["top"], ["left"], ["top", "left"]];
  function overlaps(a, b) { return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom; }
  function dodge() {
    if (!card || !card.isConnected) return;
    const targets = [submitButton(), ...document.querySelectorAll('button[type="submit"], input[type="submit"]')]
      .filter((b) => b && visible(b)).map((b) => b.getBoundingClientRect());
    if (!targets.length) return;
    for (const c of CORNERS) {
      card.classList.toggle("top", c.includes("top"));
      card.classList.toggle("left", c.includes("left"));
      const r = card.getBoundingClientRect();
      if (!targets.some((t) => overlaps(r, t))) return;
    }
    minimized = true; card.classList.add("min");  // nowhere free: shrink to the header bar
  }
  let dodgeTimer = null;
  addEventListener("scroll", () => { clearTimeout(dodgeTimer); dodgeTimer = setTimeout(dodge, 120); }, { passive: true });
  addEventListener("resize", () => { clearTimeout(dodgeTimer); dodgeTimer = setTimeout(dodge, 120); });

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function draw(note, tone) {
    if (window.top !== window && !fields.size) return;
    ensurePanel();
    card.classList.toggle("min", minimized);
    card.textContent = "";
    const total = Object.keys(filled).length + unresolved.length;
    const head = el("div", "head");
    head.append(el("span", "dot" + (offline ? " off" : unresolved.length ? " warn" : "")));
    const t = el("div", "title");
    t.append(el("div", "brand", "ApplyBot Live"), el("div", null, offline ? "Not connected" : (job ? job.company + " · " + job.title : "Filling this form")));
    head.append(t, el("span", "chev", "▾"));
    head.addEventListener("click", () => { minimized = !minimized; card.classList.toggle("min", minimized); });
    card.append(head);
    const body = el("div", "body");
    card.append(body);
    if (offline) {
      body.append(el("div", "note bad", "Open the Claude desktop app, then reload this page."));
      return;
    }
    const bar = el("div", "bar"), fillEl = el("div", "fill");
    fillEl.style.width = (total ? Math.round(100 * Object.keys(filled).length / total) : 0) + "%";
    bar.append(fillEl);
    const stats = el("div", "stats");
    const a = el("span"); a.append(el("b", null, String(Object.keys(filled).length)), document.createTextNode(" filled"));
    const b = el("span"); b.append(el("b", null, String(unresolved.length)), document.createTextNode(unresolved.length === 1 ? " needs you" : " need you"));
    stats.append(a, b);
    body.append(bar, stats);
    if (note) {
      const n = el("div", "note" + (tone ? " " + tone : ""));
      if (tone === "ok") n.append(el("span", "check", "✓"), document.createTextNode("  " + note)); else n.textContent = note;
      body.append(n);
    }
    if (countdownLeft > 0) {
      const ring = el("div", "ring");
      const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg"), r = 14, len = 2 * Math.PI * r;
      svg.setAttribute("viewBox", "0 0 34 34");
      for (const cls of ["bg", "fg"]) {
        const c = document.createElementNS(NS, "circle");
        c.setAttribute("cx", 17); c.setAttribute("cy", 17); c.setAttribute("r", r); c.setAttribute("class", cls);
        if (cls === "fg") { c.style.strokeDasharray = len; c.style.strokeDashoffset = len * (1 - countdownLeft / 5); }
        svg.append(c);
      }
      const stop = el("button", "cancel", "Cancel");
      stop.addEventListener("click", (e) => { e.stopPropagation(); cancelled = true; countdownLeft = 0; draw("Auto-submit cancelled - submit when you're ready."); });
      ring.append(svg, el("span", null, "Submitting in " + countdownLeft + "s"), stop);
      body.append(ring);
    }
    const needSig = unresolved.join(",");
    for (const key of unresolved.slice(0, 12)) {
      const f = fields.get(key);
      if (!f) continue;
      const btn = el("button", "need", (f.label || "Unlabelled question").slice(0, 80));
      if (needSig === lastNeed) btn.style.animation = "none";      // only animate when the list changes
      btn.addEventListener("click", (e) => { e.stopPropagation(); f.els[0].scrollIntoView({ block: "center", behavior: "smooth" }); f.els[0].focus && f.els[0].focus(); });
      body.append(btn);
    }
    lastNeed = needSig;
    requestAnimationFrame(dodge);
  }

  // a quick green flash on each field as the bot fills it
  function flash(key) {
    const f = fields.get(key);
    for (const e of (f && f.els) || []) {
      try {
        e.animate([{ boxShadow: "0 0 0 0 rgba(81,207,102,.0)" }, { boxShadow: "0 0 0 4px rgba(81,207,102,.55)" },
                   { boxShadow: "0 0 0 0 rgba(81,207,102,.0)" }], { duration: 700, easing: "ease-out" });
      } catch (err) { /* very old engines */ }
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
    pendingFiles = (resp.fill || []).filter((i) => i.file)
      .map((i) => ({ label: (list.find((f) => f.key === i.key) || {}).label, file: i.file, tries: 0 }));
    pendingVals = (resp.fill || []).filter((i) => !i.file && i.value)
      .map((i) => ({ key: i.key, value: i.value, tries: 0 }));
    for (const item of resp.fill || []) {
      const cur = list.find((f) => f.key === item.key);
      if (cur && cur.value && !item.file) { filled[item.key] = cur.value; continue; }   // never overwrite what's there
      const ok = item.file ? await attach(item.key, item.file) : await setValue(item.key, item.value);
      if (ok) { filled[item.key] = item.value || item.filename; flash(item.key); }
    }
    await report();
    window.__applybotReady = true;
    autoSubmit = !!resp.auto_submit;
    if (resp.queue_tab) markQueueTab();
    maybeAutoSubmit();
  }

  // ---- auto-submit: only when nothing required is empty and no bot check is on the page ----
  let autoSubmit = false, countdown = null, cancelled = false;
  const CAPTCHA_SEL = 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], iframe[title*="captcha" i], .g-recaptcha, .h-captcha, .cf-turnstile';

  // A challenge you have to solve stops auto-submit. The passive reCAPTCHA badge that Ashby / Greenhouse put on
  // every form (invisible, nothing to solve) does not.
  function captchaShowing() {
    return [...document.querySelectorAll(CAPTCHA_SEL)].some((el) => {
      if (el.closest(".grecaptcha-badge") || /size=invisible/.test(el.src || "")) return false;
      if (el.matches(".g-recaptcha") && el.getAttribute("data-size") === "invisible") return false;
      return visible(el) && el.offsetWidth > 60 && el.offsetHeight > 30;
    });
  }

  // The real submit button: one that says "submit" beats a bare "Apply" (Greenhouse has an "Apply" jump link at the
  // top of the page), and a type=submit button inside a form beats one outside it.
  function submitButton() {
    const score = (b) => {
      const t = (b.innerText || b.value || "").trim();
      return (/submit/i.test(t) ? 4 : 0) + (b.type === "submit" ? 2 : 0) + (b.closest("form") ? 1 : 0);
    };
    return [...document.querySelectorAll('button, input[type="submit"]')]
      .filter((b) => visible(b) && !b.disabled && SUBMIT_RE.test(b.innerText || b.value || ""))
      .sort((a, b) => score(b) - score(a))[0];
  }

  function maybeAutoSubmit() {
    if (!autoSubmit || cancelled || countdown || done) return;
    const btn = submitButton();
    if (!btn || unresolved.length || captchaShowing()) return;
    countdownLeft = 5;
    draw("Everything's filled.");
    countdown = setInterval(() => {
      if (cancelled || unresolved.length) { clearInterval(countdown); countdown = null; countdownLeft = 0; draw(); return; }
      countdownLeft -= 1;
      if (countdownLeft <= 0) {
        clearInterval(countdown); countdown = null;
        draw("Submitting…");
        btn.click();
        return;
      }
      draw("Everything's filled.");
    }, 1000);
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
    if (offline || (!fields.size && !isQueueTab())) return;   // the queue's tab listens even with no form (to move on)
    const got = await send({ type: "commands" });
    for (const c of (got && got.commands) || []) {
      if (c.goto) { markQueueTab(); window.top.location.href = c.goto; return; }
      if (c.focus) { send({ type: "focus" }); continue; }
      if (await setValue(c.key, c.value)) { filled[c.key] = c.value; flash(c.key); }
    }
    await retryFiles();
    await report();
    maybeAutoSubmit();
  }

  // Greenhouse re-renders its upload box once React wakes up, throwing away a file attached too early. If a file
  // we attached is still missing, attach it again to the fresh input (a few tries, a few seconds apart).
  let pendingFiles = [], pendingVals = [], lastFileTry = 0;
  async function retryFiles() {
    if ((!pendingFiles.length && !pendingVals.length) || Date.now() - lastFileTry < 4000) return;
    lastFileTry = Date.now();
    const list = scan();
    // dropdowns whose options load late (Greenhouse "State") sometimes don't take the first time: try again
    for (const p of pendingVals) {
      if (p.tries >= 3) continue;
      const f = list.find((x) => x.key === p.key);
      if (!f || f.value) continue;
      p.tries += 1;
      if (await setValue(p.key, p.value)) { filled[p.key] = p.value; flash(p.key); }
    }
    for (const p of pendingFiles) {
      if (p.tries >= 4 || !p.label) continue;
      const f = list.find((x) => x.kind === "file" && x.label === p.label && !x.value);
      if (!f) continue;
      p.tries += 1;
      if (await attach(f.key, p.file)) { filled[f.key] = p.file; flash(f.key); }
    }
  }

  // ---- stuck? move on, and leave the job on your "Needs you" list --------------------------------------------
  // Only in the tab that is working through the queue (old tabs you kept open never skip themselves).
  // Firefox wipes window.name when the tab moves to another site, so the extension remembers which tab it is.
  let queueTab = false;
  function markQueueTab() { queueTab = true; send({ type: "markQueue" }); }
  function isQueueTab() { return queueTab; }
  send({ type: "isQueue" }).then((r) => { if (r && r.queue) queueTab = true; }).catch(() => {});
  const DEAD_RE = /no longer (accepting|available|open)|job (is )?not found|position has been filled|page (you.re looking for|not found)|404/i;
  let lastSig = "", stableSince = Date.now(), stuckSent = false;
  const pageStart = Date.now();
  function checkStuck() {
    if (stuckSent || done || !isQueueTab()) return;
    const sig = unresolved.join(",") + "|" + Object.keys(filled).length;
    if (sig !== lastSig) { lastSig = sig; stableSince = Date.now(); }
    const idle = Date.now() - stableSince;
    const dead = /[?&]error=true/.test(location.href) || (!unresolved.length && !Object.keys(filled).length &&
      DEAD_RE.test(document.body ? document.body.innerText.slice(0, 3000) : ""));
    let reason = "";
    if (dead && idle > 8000) reason = "posting looks closed";
    else if (!fields.size && Date.now() - pageStart > 25000) reason = "no application form on this page";
    else if (unresolved.length && (idle > 90000 || Date.now() - pageStart > 240000)) {   // or 4 min on one form, period
      const labels = unresolved.map((k) => (fields.get(k) || {}).label).filter(Boolean).slice(0, 4);
      reason = "needs: " + labels.join("; ");
    } else if (!unresolved.length && !countdown && submitButton() && (idle > 120000 || Date.now() - pageStart > 240000))
      reason = "filled but didn't submit";
    if (!reason) return;
    stuckSent = true;
    draw("Stuck (" + reason + ") - saved to your list, moving on…", "warn");
    send({ type: "control", data: { action: "skip", reason } });
  }
  setInterval(checkStuck, 5000);

  let done = false;
  async function confirmed() {
    if (done) return;
    done = true;
    const got = await send({ type: "confirmed", data: { url: location.href } });
    if (got && got.next) {
      draw("Applied - opening the next job…", "ok");
      setTimeout(() => { markQueueTab(); window.top.location.href = got.next; }, 1200);
    } else if (got && !got.offline) {
      draw(got.applied ? "Applied - that was the last one in the queue." : "Applied", "ok");
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
