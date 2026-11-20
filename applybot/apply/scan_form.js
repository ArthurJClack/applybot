// Scans a document for fillable form controls, tags them with data-ab attributes, and describes them.
// Looks inside open shadow roots too (SmartRecruiters and other web-component forms), and reads question text
// that sits in a sibling element with no <label> link (Rippling and other CSS-in-JS forms).
() => {
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const isVisible = el => {
    if (!el.isConnected) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  // Every element matching sel in the document and in all open shadow roots, in document order.
  const deepAll = (sel, root = document, out = []) => {
    for (const e of root.querySelectorAll('*')) {
      if (e.matches(sel)) out.push(e);
      if (e.shadowRoot) deepAll(sel, e.shadowRoot, out);
    }
    return out;
  };
  // Parent that crosses shadow-root boundaries.
  const up = e => e.parentElement || (e.getRootNode && e.getRootNode() instanceof ShadowRoot ? e.getRootNode().host : null);
  const textOfIds = (el, ids) => {
    const root = el.getRootNode && el.getRootNode().getElementById ? el.getRootNode() : document;
    return ids.split(/\s+/).map(id => { const e = root.getElementById(id) || document.getElementById(id);
      return e ? e.innerText : ''; }).join(' ');
  };
  // Generic widget names some sites put in aria-label - they say nothing about the question.
  const JUNK = /^(select\.*|select one|select an option|choose\.*|search|combobox|textbox|listbox|input|text|please select|choose a file or drop it here|drop or select.*|--+)$/i;
  const ownLabel = el => {
    let t = '';
    if (el.labels && el.labels.length) t = Array.from(el.labels).map(l => l.innerText).join(' ');
    if (!clean(t) && el.getAttribute('aria-labelledby')) t = textOfIds(el, el.getAttribute('aria-labelledby'));
    if (!clean(t) && el.getAttribute('aria-label')) t = el.getAttribute('aria-label');
    t = clean(t);
    return JUNK.test(t) ? '' : t;
  };
  const LABEL_SEL = 'legend, label, [class*="label"], [class*="Label"], [class*="question"], [class*="Question"], h3, h4, h5';
  const HAS_CONTROL = 'input, select, textarea, [role=combobox], [role=radiogroup]';
  const containerLabel = (el, exclude) => {
    let p = up(el);
    for (let i = 0; i < 6 && p; i++, p = up(p)) {
      for (const cand of p.querySelectorAll(LABEL_SEL)) {
        if (cand.contains(el) && cand.tagName !== 'FIELDSET') continue;
        if (exclude && exclude.some(x => x === cand || cand.contains(x) || x.contains(cand))) continue;
        if (cand.tagName === 'LABEL' && cand.control && cand.control !== el) continue;
        if (cand.querySelector('input, select, textarea')) continue;
        const t = clean(cand.innerText);
        if (t && !JUNK.test(t)) return t;
      }
    }
    return '';
  };
  // Nearest text BEFORE the field: walk up the tree; at each level look at earlier siblings that hold no control.
  const prevText = el => {
    let p = el;
    for (let i = 0; i < 8 && p; i++, p = up(p)) {
      for (let s = p.previousElementSibling; s; s = s.previousElementSibling) {
        if (s.querySelector && s.querySelector(HAS_CONTROL)) return '';  // reached the previous question
        const t = clean(s.innerText);
        if (t && !JUNK.test(t)) return t.slice(0, 300);
      }
    }
    return '';
  };
  // Custom-element / test-id names around a file input ("oc-resume-upload") say what the upload is for.
  const hostHints = el => {
    const hints = [];
    let p = up(el);
    for (let i = 0; i < 8 && p; i++, p = up(p)) {
      const tag = p.tagName.toLowerCase(), tid = p.getAttribute && (p.getAttribute('data-testid') || p.id || '');
      for (const s of [tag, tid]) if (/resume|cv|cover|transcript/i.test(s || '')) hints.push(s);
    }
    return hints.join(' ');
  };
  const isRequired = (el, label) =>
    !!(el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$|\*\s|\(required\)/i.test(label || ''));

  deepAll('[data-ab]').forEach(e => { e.removeAttribute('data-ab'); e.removeAttribute('data-ab-opt'); });

  const out = [];
  let n = 0;
  const groups = {};
  const SKIP = new Set(['hidden', 'submit', 'button', 'image', 'reset', 'search']);

  for (const el of deepAll('input, select, textarea')) {
    const type = (el.getAttribute('type') || (el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : 'text')).toLowerCase();
    if (SKIP.has(type) || el.disabled) continue;
    // Widget proxies (e.g. react-select's hidden "required" input) are not user-fillable.
    // (Not radios/checkboxes: Workable & co. hide the real input from screen readers behind a styled role=radio.)
    if (!['file', 'radio', 'checkbox'].includes(type) && el.getAttribute('aria-hidden') === 'true' && el.tabIndex < 0) continue;
    if (type === 'radio' || type === 'checkbox') {
      const lab = el.labels && el.labels[0];
      // custom-styled radios hide the real input (0x0) inside a visible option row
      const box = el.parentElement, row = box && box.parentElement;
      if (!isVisible(el) && !(lab && isVisible(lab)) && !(box && isVisible(box)) && !(row && isVisible(row))) continue;
      const gname = el.name || (el.closest('[role=radiogroup], [role=group], fieldset') || {}).id || '';
      const gkey = type + ':' + gname;
      const root = el.getRootNode();
      if (gname && root.querySelectorAll(`input[type=${type}][name="${CSS.escape(el.name)}"]`).length > 1) {
        (groups[gkey] = groups[gkey] || []).push(el);
        continue;
      }
      if (type === 'radio') { (groups[gkey + ':' + n] = [el]); continue; }
      let label = ownLabel(el) || containerLabel(el) || prevText(el);
      // Lever-style "I certify ... [ ] Yes": the checkbox's own label is just the answer word.
      if (/^(yes|i agree|agree|i accept|accept|i acknowledge|acknowledged?|confirm(ed)?)$/i.test(label)) {
        const q = containerLabel(el, Array.from(el.labels || []).concat([el])) || prevText(el);
        if (q) label = q;
      }
      el.setAttribute('data-ab', String(n));
      out.push({ n: n++, kind: 'checkbox', label, name: el.name || '', required: isRequired(el, label),
                 options: null, value: el.checked ? 'checked' : '', placeholder: '' });
      continue;
    }
    if (type !== 'file' && (!isVisible(el) || el.readOnly)) continue;
    const role = el.getAttribute('role');
    let kind = type === 'select' ? 'select' : type === 'textarea' ? 'textarea' : type === 'file' ? 'file'
      : (role === 'combobox' || el.getAttribute('aria-autocomplete') === 'list') ? 'combobox'
      : ['email', 'tel', 'url', 'number', 'date', 'month'].includes(type) ? type : 'text';
    // text right before the field beats a wide container search, which can reach the PREVIOUS question's label
    const label = ownLabel(el) || prevText(el) || containerLabel(el) || clean(el.placeholder) || clean(el.name);
    let options = null;
    if (kind === 'select') {
      options = Array.from(el.options).map(o => clean(o.text)).filter(Boolean);
      if (el.multiple) kind = 'multiselect';
    }
    const name = kind === 'file' ? clean((el.name || el.id || '') + ' ' + hostHints(el)) : (el.name || el.id || '');
    el.setAttribute('data-ab', String(n));
    out.push({ n: n++, kind, label, name, required: isRequired(el, label), options,
               value: kind === 'file' ? (el.files && el.files.length ? 'file' : '')
                      : kind === 'select' ? (el.selectedIndex > 0 ? clean(el.options[el.selectedIndex].text) : '')
                      : (el.value || ''),
               placeholder: clean(el.placeholder), accept: el.getAttribute('accept') || '' });
  }

  // Custom dropdowns with no <select>/<input> behind them (Rippling, many design systems):
  // a div/button with role=combobox or aria-haspopup=listbox that opens a [role=listbox] of [role=option]s.
  for (const el of deepAll('[role=combobox], button[aria-haspopup=listbox]')) {
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) || el.hasAttribute('data-ab')) continue;
    if (el.querySelector('input, select, textarea') || !isVisible(el)) continue;
    if (el.getAttribute('aria-disabled') === 'true') continue;
    const label = ownLabel(el) || prevText(el) || containerLabel(el);
    const shown = clean(el.innerText);
    el.setAttribute('data-ab', String(n));
    out.push({ n: n++, kind: 'dropdown', label, name: el.id || '', required: isRequired(el, label), options: null,
               value: JUNK.test(shown) ? '' : shown, placeholder: '' });
  }

  // Button-only yes/no questions (e.g. Ashby): two sibling <button>s "Yes" / "No" with no form input behind them.
  const seenYesNo = new Set();
  for (const btn of deepAll('button')) {
    if (clean(btn.innerText).toLowerCase() !== 'yes' || !isVisible(btn)) continue;
    const grp = btn.parentElement;
    if (!grp || seenYesNo.has(grp)) continue;
    const btns = Array.from(grp.children).filter(e => e.tagName === 'BUTTON');
    if (btns.length !== 2 || !btns.some(b => clean(b.innerText).toLowerCase() === 'no')) continue;
    let near = grp.parentElement, tagged = false;
    for (let i = 0; i < 2 && near; i++, near = near.parentElement) {
      if (near.querySelector('input[data-ab], select[data-ab], textarea[data-ab]')) { tagged = true; break; }
    }
    if (tagged) continue;  // a hidden checkbox already represents this question
    seenYesNo.add(grp);
    const label = containerLabel(grp, btns) || prevText(grp);
    grp.setAttribute('data-ab', String(n));
    btns.forEach((b, i) => b.setAttribute('data-ab-opt', String(i)));
    const on = btns.find(b => b.getAttribute('aria-pressed') === 'true' || /active|selected|checked/i.test(b.className));
    out.push({ n: n++, kind: 'yesno', label, name: '', required: isRequired(grp, label),
               options: btns.map(b => clean(b.innerText)), value: on ? clean(on.innerText) : '', placeholder: '' });
  }

  for (const [gkey, els] of Object.entries(groups)) {
    const type = gkey.split(':')[0];
    const optLabels = els.map(e => ownLabel(e) || clean(e.value));
    const labelEls = els.flatMap(e => Array.from(e.labels || []));
    let question = '';
    const fs = els[0].closest('fieldset');
    if (fs && fs.querySelector('legend')) question = clean(fs.querySelector('legend').innerText);
    if (!question) {
      const rg = els[0].closest('[role=radiogroup], [role=group]');
      if (rg) question = ownLabel(rg);
    }
    if (!question) question = containerLabel(els[0], labelEls.concat(els));
    if (!question) {
      // climb to the element that holds the whole group, then read the text before it
      let box = els[0];
      while (up(box) && !els.every(e => up(box).contains(e))) box = up(box);
      question = prevText(up(box) || box);
    }
    if (els.length === 1 && type === 'radio') question = question || optLabels[0];
    els.forEach((e, i) => { e.setAttribute('data-ab', String(n)); e.setAttribute('data-ab-opt', String(i)); });
    const checked = els.filter(e => e.checked).map((e, i) => optLabels[els.indexOf(e)]);
    out.push({ n: n++, kind: type === 'radio' ? 'radio' : 'checkbox_group', label: question, name: els[0].name || '',
               required: els.some(e => e.required || e.getAttribute('aria-required') === 'true') || /\*/.test(question),
               options: optLabels, value: checked.join(', '), placeholder: '' });
  }
  return out;
}
