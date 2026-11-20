"""Regression tests for form styles found on live sites on 2026-10-28:
Rippling-style CSS-in-JS forms (question text in a sibling div, custom role=combobox dropdowns, final "Apply"
button, cookie banner overlay), SmartRecruiters-style web components (shadow DOM), bot checks at submit, and
assist mode (the person finishes the form; ApplyBot watches for the confirmation page)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from applybot.answers import AnswerBank
from conftest import FakeLLM

SEND_JS = """
function post(d) {
  fetch('/submit', {method: 'POST', body: JSON.stringify(d)}).then(r => r.text()).then(t => {
    if (t === 'bot') { const e = document.createElement('div'); e.setAttribute('role', 'alert');
      e.innerText = 'Please try again.'; document.body.appendChild(e); }
    else document.body.innerHTML = '<h1>Thank you for applying!</h1>';
  });
}"""

RIPPLING_HTML = """<!doctype html><html><body>
<div id="cookie" style="position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:50">
  <div style="position:absolute;bottom:0;width:100%;background:#fff;padding:10px">This site uses cookies.
    <button onclick="document.getElementById('cookie').remove()">Accept all</button>
    <button onclick="document.getElementById('cookie').remove()">Decline all</button></div></div>
<h2>Application: Backend Intern</h2>
<form id="f">
 <div class="css-a1"><div class="css-q">First name*</div><div class="css-c"><input name="x1" placeholder="First name" required></div></div>
 <div class="css-a1"><div class="css-q">Last name*</div><div class="css-c"><input name="x2" placeholder="Last name" required></div></div>
 <div class="css-a1"><div class="css-q">Are you able to intern full time from May to August 2027?*</div>
   <div><div class="css-s"><div id="dd1" role="combobox" aria-haspopup="listbox" aria-expanded="false" aria-controls="dd1-list"
        aria-label="Select" aria-required="true" tabindex="0" data-opts="Yes|No"><p>Select</p></div></div></div></div>
 <div class="css-a1"><div class="css-q">Will you now or in the future require sponsorship?*</div>
   <div class="css-grp">
     <div class="css-o"><div class="css-r"><input type="radio" id="r1" name="spons" value="Yes"
          style="opacity:0;width:0;height:0;position:absolute"></div><label for="r1" style="display:none">Yes</label><span>Yes</span></div>
     <div class="css-o"><div class="css-r"><input type="radio" id="r2" name="spons" value="No"
          style="opacity:0;width:0;height:0;position:absolute"></div><label for="r2" style="display:none">No</label><span>No</span></div>
   </div></div>
 <div class="css-a1"><span id="g-label">Gender</span>
   <div id="dd2" role="combobox" aria-haspopup="listbox" aria-controls="dd2-list" aria-labelledby="g-label"
        tabindex="0" data-opts="Male|Female|Decline to self-identify"><p>Select...</p></div></div>
 <button type="submit" id="go" disabled>Apply</button>
</form>
<script>
""" + SEND_JS + """
const val = {};
function closeAll() { document.querySelectorAll('[role=listbox]').forEach(l => l.remove()); }
document.querySelectorAll('[role=combobox]').forEach(dd => dd.addEventListener('click', () => {
  closeAll(); dd.setAttribute('aria-expanded', 'true');
  const ul = document.createElement('ul'); ul.id = dd.getAttribute('aria-controls'); ul.setAttribute('role', 'listbox');
  for (const o of dd.dataset.opts.split('|')) {
    const li = document.createElement('li'); li.setAttribute('role', 'option'); li.innerText = o;
    li.onclick = () => { dd.querySelector('p').innerText = o; val[dd.id] = o; closeAll(); check(); };
    ul.appendChild(li);
  }
  document.body.appendChild(ul);
}));
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(); });
function check() { document.getElementById('go').disabled = !(document.querySelector('[name=x1]').value && val.dd1); }
document.querySelector('[name=x1]').addEventListener('input', check);
document.getElementById('f').addEventListener('submit', e => {
  e.preventDefault();
  const s = document.querySelector('[name=spons]:checked');
  post({first: document.querySelector('[name=x1]').value, last: document.querySelector('[name=x2]').value,
        fulltime: val.dd1, gender: val.dd2, spons: s ? s.value : ''});
});
</script></body></html>"""

SHADOW_HTML = """<!doctype html><html><body>
<h2>Easy apply</h2>
<script>
customElements.define('x-input', class extends HTMLElement {
  connectedCallback() {
    const r = this.attachShadow({mode: 'open'});
    r.innerHTML = `<label for="i">${this.getAttribute('label')}${this.hasAttribute('req') ? '*' : ''}</label>
                   <input id="i" type="${this.getAttribute('type') || 'text'}">`;
  }
  get value() { return this.shadowRoot.querySelector('input').value; }
});
customElements.define('x-resume-upload', class extends HTMLElement {
  connectedCallback() {
    const r = this.attachShadow({mode: 'open'});
    r.innerHTML = `<label for="f">Choose a file or drop it here</label><input id="f" type="file" style="display:none">`;
  }
  get value() { const f = this.shadowRoot.querySelector('input').files; return f.length ? f[0].name : ''; }
});
</script>
<x-input id="fn" label="First name" req></x-input>
<x-input id="ln" label="Last name" req></x-input>
<x-input id="em" label="Email" type="email" req></x-input>
<x-resume-upload id="cv"></x-resume-upload>
<button onclick="post({first: fn.value, last: ln.value, email: em.value, resume: cv.value})">Submit application</button>
<script>""" + SEND_JS + """</script>
</body></html>"""

# The "person" finishing in assist mode is simulated by the page: once ApplyBot has filled the first name,
# it "clicks submit" a moment later.
ASSIST_HTML = """<!doctype html><html><body><h2>Apply</h2>
<label for="fn">First name *</label><input id="fn" name="first" required>
<label for="code">Security code (we emailed it to you) *</label><input id="code" name="code" required>
<button id="go" onclick="post({first: fn.value, code: code.value})">Submit application</button>
<script>""" + SEND_JS + """
fn.addEventListener('input', () => setTimeout(() => { code.value = '123456'; go.click(); }, 1500));
</script></body></html>"""


@pytest.fixture
def site():
    received, state = [], {"bot": False}
    pages = {"/rippling": RIPPLING_HTML, "/shadow": SHADOW_HTML, "/assist": ASSIST_HTML,
             "/idle": ASSIST_HTML.replace("setTimeout(", "void("), "/workable": WORKABLE_HTML}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = pages.get(self.path.split("?")[0], "<h1>nothing</h1>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n))
            self.send_response(200)
            self.end_headers()
            if state["bot"]:
                self.wfile.write(b"bot")
                return
            received.append(data)
            self.wfile.write(b"ok")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", received, state
    srv.shutdown()


def _cfg(tmp_path, **apply):
    import copy
    from applybot.config import DEFAULTS, Config
    cfg = Config(copy.deepcopy(DEFAULTS))
    cfg.base_dir = tmp_path
    cfg["apply"]["headless"] = True
    cfg["apply"].update(apply)
    return cfg


def _bank(tmp_path, profile):
    (tmp_path / "answers.yaml").write_text(
        "work_authorization:\n  authorized_to_work: 'Yes'\n  requires_sponsorship: 'No'\n"
        "eeo:\n  gender: Male\nauto_consent: true\ncustom:\n  able to intern full time: 'Yes'\n")
    return AnswerBank(tmp_path / "answers.yaml", profile)


def _run(tmp_path, profile, job, url, mode, files=None, **apply):
    pytest.importorskip("playwright")
    from applybot.apply.browser import Applicant
    with Applicant(_cfg(tmp_path, **apply), profile, _bank(tmp_path, profile), FakeLLM(lambda p: {"answers": {}}),
                   log=lambda *a: None) as app:
        return app.apply(url, job, files or {}, mode, tmp_path / "shots")


def test_rippling_style_form(tmp_path, site, profile, job):
    base, received, _ = site
    res = _run(tmp_path, profile, job, f"{base}/rippling", "auto")
    assert res.status == "applied", res.notes
    assert received == [{"first": "Alex", "last": "Rivera", "fulltime": "Yes", "gender": "Male", "spons": "No"}]


def test_shadow_dom_form(tmp_path, site, profile, job):
    base, received, _ = site
    resume = tmp_path / "Alex_Rivera_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test")
    res = _run(tmp_path, profile, job, f"{base}/shadow", "auto", {"resume": resume})
    assert res.status == "applied", res.notes
    assert received == [{"first": "Alex", "last": "Rivera", "email": "alex.rivera@example.com",
                         "resume": "Alex_Rivera_Resume.pdf"}]


def test_bot_check_at_submit_points_to_assist(tmp_path, site, profile, job):
    base, received, state = site
    state["bot"] = True
    res = _run(tmp_path, profile, job, f"{base}/rippling", "auto")
    assert res.status == "needs_review"
    assert "assist" in res.notes and received == []


def test_assist_mode_waits_for_the_person(tmp_path, site, profile, job):
    base, received, _ = site
    res = _run(tmp_path, profile, job, f"{base}/assist", "assist", assist_minutes=0.5)
    assert res.status == "applied", res.notes
    assert "assist" in res.notes
    # ApplyBot filled the name but never typed the code - the "person" did
    assert received == [{"first": "Alex", "code": "123456"}]


def test_assist_mode_times_out_without_submitting(tmp_path, site, profile, job):
    base, received, _ = site
    res = _run(tmp_path, profile, job, f"{base}/idle", "assist", assist_minutes=0.1)
    assert res.status == "needs_review" and "no confirmation" in res.notes
    assert received == []  # ApplyBot never clicks submit in assist mode


WORKABLE_HTML = """<!doctype html><html><body><h2>Details</h2><form id="f">
<label for="fn">First name *</label><input id="fn" name="firstname" required>
<div><span><strong>*</strong></span><span id="q1_label"><strong>Are you authorized to work in the United States now and in
 the future without requiring employer sponsorship for an employment visa, such as an H-1B?</strong></span>
<fieldset role="radiogroup" aria-labelledby="q1_label">
 <div role="radio" aria-checked="false"><label><input aria-hidden="true" tabindex="-1" required type="radio" name="QA_1"
   value="true"><span>YES</span></label></div>
 <div role="radio" aria-checked="false"><label><input aria-hidden="true" tabindex="-1" required type="radio" name="QA_1"
   value="false"><span>NO</span></label></div></fieldset></div>
<div><span id="q2_label">Do you require work authorization to work in the United States for this internship?*</span>
<fieldset role="radiogroup" aria-labelledby="q2_label">
 <div role="radio"><label><input aria-hidden="true" tabindex="-1" required type="radio" name="QA_2" value="true">
   <span>YES</span></label></div>
 <div role="radio"><label><input aria-hidden="true" tabindex="-1" required type="radio" name="QA_2" value="false">
   <span>NO</span></label></div></fieldset></div>
<button type="button" onclick="post({first: fn.value,
  q1: (document.querySelector('[name=QA_1]:checked') || {}).value || '',
  q2: (document.querySelector('[name=QA_2]:checked') || {}).value || ''})">Submit application</button>
</form><script>""" + SEND_JS + """</script></body></html>"""


def test_workable_hidden_radios_and_sponsorship_wording(tmp_path, site, profile, job):
    base, received, _ = site
    res = _run(tmp_path, profile, job, f"{base}/workable", "auto")
    assert res.status == "applied", res.notes
    # authorized WITHOUT sponsorship -> yes; "require work authorization" means sponsorship -> no
    assert received == [{"first": "Alex", "q1": "true", "q2": "false"}]


def test_question_wording_regressions():
    from applybot.answers import classify
    auth, spons = "work_authorization.authorized_to_work", "work_authorization.requires_sponsorship"
    assert classify("Are you authorized to work in the United States now and in the future without requiring "
                    "employer sponsorship for an employment visa, such as an H-1B?") == auth
    assert classify("Can you work in the U.S. without the need for visa sponsorship?") == auth
    assert classify("Do you require work authorization to work in the United States for this internship?") == spons
    assert classify("Would you require work authorization support to work full-time after graduation?") == spons
    assert classify("Will you now or in the future require sponsorship?") == spons
    assert classify("Do you have professional experience with Django (excluding school projects)?") != "school"
    assert classify("Do you have a high school diploma or GED?") != "school"
    assert classify("What school or university are you attending?") == "school"


def test_number_only_salary_is_left_for_the_person(tmp_path, profile):
    from applybot.answers import AnswerBank, Field, resolve_fields
    (tmp_path / "a.yaml").write_text("logistics:\n  salary_expectation: Open / negotiable\n")
    bank = AnswerBank(tmp_path / "a.yaml", profile)
    f = Field("1", "text", "What is your expected annual base salary in USD? Please enter a number only (e.g., 70000).", True)
    g = Field("2", "text", "What is your desired salary?", True)
    r = resolve_fields([f, g], bank, profile, {"title": "x", "company": "y"}, None)
    assert r["1"].value is None and r["2"].value == "Open / negotiable"
