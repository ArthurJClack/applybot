import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from applybot.answers import AnswerBank
from conftest import FakeLLM

FORM_HTML = """<!doctype html><html><body>
<h1>Apply: Backend Intern</h1>
<form id="f" onsubmit="return false">
 <div id="step1">
  <label for="fn">First Name *</label><input id="fn" name="first_name" required>
  <label for="ln">Last Name *</label><input id="ln" name="last_name" required>
  <label for="em">Email *</label><input id="em" type="email" name="email" required>
  <div class="field"><div class="label">Phone</div><input name="phone" type="tel"></div>
  <label>Resume/CV <input type="file" id="resume" name="resume" style="display:none"></label>
  <button type="button" onclick="document.getElementById('step1').style.display='none';
     document.getElementById('step2').style.display='block'">Next</button>
 </div>
 <div id="step2" style="display:none">
  <label for="school">School</label><input id="school" name="school">
  <fieldset><legend>Are you legally authorized to work in the US? *</legend>
    <label><input type="radio" name="auth" value="y" required> Yes</label>
    <label><input type="radio" name="auth" value="n"> No</label></fieldset>
  <fieldset><legend>Will you now or in the future require sponsorship? *</legend>
    <label><input type="radio" name="spons" value="y"> Yes</label>
    <label><input type="radio" name="spons" value="n"> No</label></fieldset>
  <label for="g">Gender</label>
  <select id="g" name="gender"><option>Select...</option><option>Male</option><option>Female</option>
    <option>I don't wish to answer</option></select>
  <label for="why">Why do you want to work at Widgets Inc? *</label><textarea id="why" name="why" required></textarea>
  <label><input type="checkbox" name="privacy" required> I agree to the privacy policy</label>
  <button type="button" id="submit" onclick="send()">Submit Application</button>
 </div>
</form>
<script>
function send(){
  const f = document.getElementById('f'); const d = {};
  for (const el of f.elements) {
    if (!el.name) continue;
    if (el.type === 'radio') { if (el.checked) d[el.name] = el.parentElement.innerText.trim(); }
    else if (el.type === 'checkbox') d[el.name] = el.checked;
    else if (el.type === 'file') d[el.name] = el.files.length ? el.files[0].name : '';
    else if (el.tagName === 'SELECT') d[el.name] = el.options[el.selectedIndex].text;
    else d[el.name] = el.value;
  }
  fetch('/submit', {method: 'POST', body: JSON.stringify(d)}).then(() => {
    document.body.innerHTML = '<h1>Thank you for applying!</h1>';
  });
}
</script></body></html>"""

LANDING_HTML = """<!doctype html><html><body><h1>Backend Intern</h1><p>Great job.</p>
<a href="/form">Apply for this job</a></body></html>"""


@pytest.fixture
def server():
    received = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = (FORM_HTML if self.path.startswith("/form") else LANDING_HTML).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(n)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", received
    srv.shutdown()


def _cfg(tmp_path):
    from applybot.config import DEFAULTS, Config
    import copy
    cfg = Config(copy.deepcopy(DEFAULTS))
    cfg.base_dir = tmp_path
    cfg["apply"]["headless"] = True
    return cfg


@pytest.mark.parametrize("mode", ["auto", "dry_run"])
def test_end_to_end_application(tmp_path, server, profile, job, mode):
    pytest.importorskip("playwright")
    from applybot.apply.browser import Applicant
    base, received = server
    resume = tmp_path / "Alex_Rivera_Resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test")

    def handler(prompt):
        payload = json.loads(prompt.split("FIELDS:")[1])
        return {"answers": {f["key"]: "I admire Widgets Inc's API platform and have built similar FastAPI services."
                            for f in payload}}
    llm = FakeLLM(handler)
    (tmp_path / "answers.yaml").write_text("work_authorization:\n  authorized_to_work: 'Yes'\n"
                                           "  requires_sponsorship: 'No'\nauto_consent: true\n")
    bank = AnswerBank(tmp_path / "answers.yaml", profile)
    with Applicant(_cfg(tmp_path), profile, bank, llm, log=lambda *a: None) as app:
        res = app.apply(f"{base}/job", job, {"resume": resume}, mode, tmp_path / "shots")

    if mode == "dry_run":
        assert res.status == "dry_run", res.notes
        assert received == []
        assert Path(res.screenshot).exists()
        return
    assert res.status == "applied", res.notes
    assert len(received) == 1
    d = received[0]
    assert d["first_name"] == "Alex" and d["last_name"] == "Rivera"
    assert d["email"] == "alex.rivera@example.com"
    assert d["phone"] == "(555) 123-4567"
    assert d["resume"] == "Alex_Rivera_Resume.pdf"
    assert d["school"] == "University of Texas at Austin"
    assert d["auth"] == "Yes" and d["spons"] == "No"
    assert d["gender"] == "I don't wish to answer"
    assert "FastAPI" in d["why"]
    assert d["privacy"] is True
    # sensitive/EEO questions never went to the AI
    assert all("Gender" not in p and "sponsorship" not in p for p in llm.prompts)


def test_auto_mode_flags_unanswerable_required(tmp_path, server, profile, job):
    pytest.importorskip("playwright")
    from applybot.apply.browser import Applicant
    base, received = server
    llm = FakeLLM(lambda p: {"answers": {}})  # AI can't answer the essay question
    bank = AnswerBank(tmp_path / "answers.yaml", profile)
    with Applicant(_cfg(tmp_path), profile, bank, llm, log=lambda *a: None) as app:
        res = app.apply(f"{base}/form", job, {}, "auto", tmp_path / "shots")
    assert res.status == "needs_review"
    assert "Why do you want" in res.notes
    assert received == []


def test_direct_form_url():
    from applybot.apply.browser import direct_form_url

    assert direct_form_url("https://job-boards.greenhouse.io/airbnb/jobs/8257855") == \
        "https://job-boards.greenhouse.io/embed/job_app?for=airbnb&token=8257855"
    assert direct_form_url("https://boards.greenhouse.io/stripe/jobs/123?gh_src=x") == \
        "https://job-boards.greenhouse.io/embed/job_app?for=stripe&token=123"
    lever = "https://jobs.lever.co/palantir/0e8a3c2d-1111-2222-3333-444455556666"
    assert direct_form_url(lever) == lever + "/apply"
    assert direct_form_url(lever + "/apply") == lever + "/apply"
    ashby = "https://jobs.ashbyhq.com/ramp/0e8a3c2d-1111-2222-3333-444455556666"
    assert direct_form_url(ashby) == ashby + "/application"
    assert direct_form_url("https://example.com/careers/42") == "https://example.com/careers/42"
