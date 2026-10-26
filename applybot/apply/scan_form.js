// Scans a document for fillable form controls, tags them with data-ab attributes, and describes them.
() => {
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const isVisible = el => {
    if (!el.isConnected) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const textOfIds = ids => ids.split(/\s+/).map(id => {
    const e = document.getElementById(id); return e ? e.innerText : '';
  }).join(' ');
  const ownLabel = el => {
    let t = '';
    if (el.labels && el.labels.length) t = Array.from(el.labels).map(l => l.innerText).join(' ');
    if (!clean(t) && el.getAttribute('aria-labelledby')) t = textOfIds(el.getAttribute('aria-labelledby'));
    if (!clean(t) && el.getAttribute('aria-label')) t = el.getAttribute('aria-label');
    return clean(t);
  };
  const LABEL_SEL = 'legend, label, [class*="label"], [class*="Label"], [class*="question"], [class*="Question"], h3, h4, h5';
  const containerLabel = (el, exclude) => {
    let p = el.parentElement;
    for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
      for (const cand of p.querySelectorAll(LABEL_SEL)) {
        if (cand.contains(el) && cand.tagName !== 'FIELDSET') continue;
        if (exclude && exclude.some(x => x === cand || cand.contains(x) || x.contains(cand))) continue;
        if (cand.tagName === 'LABEL' && cand.control && cand.control !== el) continue;
        if (cand.querySelector('input, select, textarea')) continue;
        const t = clean(cand.innerText);
        if (t) return t;
      }
    }
    return '';
  };
  const isRequired = (el, label) =>
    !!(el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$|\*\s|\(required\)/i.test(label || ''));

  document.querySelectorAll('[data-ab]').forEach(e => { e.removeAttribute('data-ab'); e.removeAttribute('data-ab-opt'); });

  const out = [];
  let n = 0;
  const groups = {};
  const SKIP = new Set(['hidden', 'submit', 'button', 'image', 'reset', 'search']);

  for (const el of document.querySelectorAll('input, select, textarea')) {
    const type = (el.getAttribute('type') || (el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : 'text')).toLowerCase();
    if (SKIP.has(type) || el.disabled) continue;
    // Widget proxies (e.g. react-select's hidden "required" input) are not user-fillable.
    if (type !== 'file' && el.getAttribute('aria-hidden') === 'true' && el.tabIndex < 0) continue;
    if (type === 'radio' || type === 'checkbox') {
      const lab = el.labels && el.labels[0];
      if (!isVisible(el) && !(lab && isVisible(lab)) && !(el.parentElement && isVisible(el.parentElement))) continue;
      const gname = el.name || (el.closest('[role=radiogroup], [role=group], fieldset') || {}).id || '';
      const gkey = type + ':' + gname;
      if (gname && document.querySelectorAll(`input[type=${type}][name="${CSS.escape(el.name)}"]`).length > 1) {
        (groups[gkey] = groups[gkey] || []).push(el);
        continue;
      }
      if (type === 'radio') { (groups[gkey + ':' + n] = [el]); continue; }
      const label = ownLabel(el) || containerLabel(el);
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
    const label = ownLabel(el) || containerLabel(el) || clean(el.placeholder) || clean(el.name);
    let options = null;
    if (kind === 'select') {
      options = Array.from(el.options).map(o => clean(o.text)).filter(Boolean);
      if (el.multiple) kind = 'multiselect';
    }
    el.setAttribute('data-ab', String(n));
    out.push({ n: n++, kind, label, name: el.name || el.id || '', required: isRequired(el, label), options,
               value: kind === 'file' ? (el.files && el.files.length ? 'file' : '')
                      : kind === 'select' ? (el.selectedIndex > 0 ? clean(el.options[el.selectedIndex].text) : '')
                      : (el.value || ''),
               placeholder: clean(el.placeholder), accept: el.getAttribute('accept') || '' });
  }

  // Button-only yes/no questions (e.g. Ashby): two sibling <button>s "Yes" / "No" with no form input behind them.
  const seenYesNo = new Set();
  for (const btn of document.querySelectorAll('button')) {
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
    const label = containerLabel(grp, btns);
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
    if (els.length === 1 && type === 'radio') question = question || optLabels[0];
    els.forEach((e, i) => { e.setAttribute('data-ab', String(n)); e.setAttribute('data-ab-opt', String(i)); });
    const checked = els.filter(e => e.checked).map((e, i) => optLabels[els.indexOf(e)]);
    out.push({ n: n++, kind: type === 'radio' ? 'radio' : 'checkbox_group', label: question, name: els[0].name || '',
               required: els.some(e => e.required) || /\*/.test(question), options: optLabels,
               value: checked.join(', '), placeholder: '' });
  }
  return out;
}
