import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from applybot.config import load_config
from applybot.db import DB
from applybot.live.bridge import LiveBridge, url_tokens
from applybot.models import Job
from applybot.pipeline import job_dir

EXT = Path(__file__).resolve().parents[1] / "applybot" / "live" / "extension"
URL = "https://job-boards.greenhouse.io/acme/jobs/4722675006"

FORM = """<!doctype html><html><body><form id="f" onsubmit="return false">
 <label for="fn">First Name *</label><input id="fn" required>
 <label for="ln">Last Name *</label><input id="ln" required>
 <label for="em">Email *</label><input id="em" type="email" required>
 <label for="pw">Password</label><input id="pw" type="password">
 <label for="cv">Resume/CV *</label><input id="cv" type="file" required>
 <label for="st">Do you currently reside in the U.S.? *</label>
 <select id="st" required><option value="">Select</option><option>Yes</option><option>No</option></select>
 <fieldset><legend>Have you built a backend application? *</legend>
   <label><input type="radio" name="be" value="y" required> Yes</label>
   <label><input type="radio" name="be" value="n"> No</label></fieldset>
 <label for="why">Why Acme? *</label><textarea id="why" required></textarea>
 <button type="button" id="go" onclick="document.body.innerHTML='<h1>Thank you for applying!</h1>'">Submit application</button>
</form></body></html>"""


@pytest.fixture
def live(tmp_path, profile):
    (tmp_path / "config.yaml").write_text("{}", encoding="utf-8")
    cfg = load_config(tmp_path / "config.yaml")
    db = DB(cfg.path("database"))
    jobs = [Job(source="greenhouse", external_id="4722675006", company="Acme", title="Backend Intern", url=URL, apply_url=URL),
            Job(source="lever", external_id="x2", company="Beta", title="SWE", url="https://jobs.lever.co/beta/11111111-2222-3333-4444-555555555555")]
    for j in jobs:
        db.upsert_job(j)
    job = db.get_job(jobs[0].id)
    d = job_dir(cfg, job)
    (d / "Arthur_Clack_Resume.pdf").write_bytes(b"%PDF-1.4 resume")
    opened = []
    bridge = LiveBridge(lambda: (cfg, profile, DB(cfg.path("database"))), opener=opened.append)  # a connection per thread
    bridge.test = {"cfg": cfg, "db": db, "job": job, "next": jobs[1], "opened": opened}
    yield bridge
    bridge.stop()


def fields():
    return [{"key": "f1", "kind": "text", "label": "First Name *", "required": True},
            {"key": "f2", "kind": "email", "label": "Email *", "required": True},
            {"key": "f3", "kind": "file", "label": "Resume/CV *", "required": True},
            {"key": "f4", "kind": "radio", "label": "Are you legally authorized to work in the US? *", "required": True,
             "options": ["Yes", "No"]},
            {"key": "f5", "kind": "text", "label": "Favorite editor *", "required": True}]


def test_url_tokens():
    assert url_tokens(URL) == ["4722675006"]
    assert url_tokens("https://jobs.lever.co/x/11111111-2222-3333-4444-555555555555/apply")


def test_page_resolves_answers_and_documents(live, profile):
    out = live.page("7", {"url": URL + "?gh_src=abc", "title": "Apply", "fields": fields()})
    assert out["job"]["company"] == "Acme"
    fill = {x["key"]: x for x in out["fill"]}
    assert fill["f1"]["value"] and fill["f2"]["value"] == profile["contact"]["email"]
    assert fill["f3"]["file"].endswith("/resume") and fill["f3"]["filename"].endswith(".pdf")
    assert "f5" in out["unresolved"]
    assert live.file_bytes(live.test["job"]["id"], "resume")[0].startswith(b"%PDF")
    assert live.file_bytes(live.test["job"]["id"], "passwords") is None


def test_live_edits_refuse_sensitive_password_and_files(live):
    data = fields() + [{"key": "f6", "kind": "password", "label": "Password"}]
    live.page("7", {"url": URL, "fields": data})
    got = live.set_fields({"Favorite editor *": "PyCharm", "Resume/CV *": "x", "nope": "1",
                           "Are you legally authorized to work in the US? *": "Yes"})
    assert got["queued"] == ["Favorite editor *"] and got["unknown"] == ["nope"] and len(got["refused"]) == 2
    assert live.take_commands("7") == {"commands": [{"key": "f5", "value": "PyCharm"}]}
    assert live.take_commands("7") == {"commands": []}
    ok = live.set_fields({"Are you legally authorized to work in the US? *": "Yes"}, confirmed_by_user=True)
    assert ok["queued"] and not ok["refused"]


def test_confirmation_marks_applied_learns_and_opens_next(live):
    t = live.test
    assert live.open_jobs([t["job"]["id"], t["next"].id]) == {"opened": URL, "queued": 1}
    assert t["opened"] == [URL]
    live.page("7", {"url": URL, "fields": fields()})
    live.submitted("7", {"url": URL, "answers": [
        {"key": "f1", "label": "First Name *", "kind": "text", "value": "Arthur"},          # bot-filled: not learned
        {"key": "f5", "label": "Favorite editor *", "kind": "text", "value": "PyCharm"},    # typed by hand: learned
        {"key": "f9", "label": "I agree to the privacy policy", "kind": "checkbox", "value": "Yes"}]})
    out = live.confirmed("7", {"url": URL})
    assert out["applied"] == t["job"]["id"] and out["learned"] == ["Favorite editor *"]
    assert out["next"].startswith("https://jobs.lever.co/beta/")
    assert t["db"].get_job(t["job"]["id"])["status"] == "applied"
    again = live.page("8", {"url": URL, "fields": fields()})
    assert {x["key"]: x for x in again["fill"]}["f5"]["value"] == "PyCharm"   # next form fills it on its own


def _req(port, path, body=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=None if body is None else json.dumps(body).encode(),
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def test_http_only_serves_the_extension(live):
    port = live.start(0)
    assert _req(port, "/live/ping")[0] == 200
    assert _req(port, "/live/ping", headers={"Origin": "https://evil.example"})[0] == 403
    assert _req(port, "/live/ping", headers={"Host": "evil.example"})[0] == 403
    body = {"tab": 1, "url": URL, "fields": fields()}
    assert _req(port, "/live/page", body)[0] == 403                                    # no extension header
    assert _req(port, "/live/page", body, {"X-ApplyBot": "1", "Origin": "https://evil.example"})[0] == 403
    code, out = _req(port, "/live/page", body, {"X-ApplyBot": "1", "Origin": "moz-extension://abc"})
    assert code == 200 and out["job"]["company"] == "Acme"


def test_content_script_fills_a_real_page(live):
    pw = pytest.importorskip("playwright.sync_api")
    t = live.test

    def send(msg):
        kind, data = msg["type"], msg.get("data", {})
        if kind == "file":
            got = live.file_bytes(*msg["path"].split("/")[-2:])
            return {"ok": bool(got), "bytes": list(got[0]), "name": got[1]} if got else {"ok": False}
        if kind == "commands":
            return live.take_commands("1")
        return getattr(live, kind)("1", data)

    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"no browser: {e}")
        page = browser.new_page()
        page.route(URL, lambda r: r.fulfill(body=FORM, content_type="text/html"))
        page.goto(URL)
        page.expose_function("__applybotSend", send)
        page.add_script_tag(path=str(EXT / "content.js"))
        page.wait_for_function("window.__applybotReady === true")
        assert page.input_value("#fn") and page.input_value("#em")
        assert page.input_value("#pw") == ""                                   # password untouched
        assert page.evaluate("document.querySelector('#cv').files[0].name").endswith("Resume.pdf")
        assert "need you" in page.evaluate("document.querySelector('#applybot-live-panel').shadowRoot.textContent")
        status = live.current()
        assert all(f["kind"] != "password" for f in status["fields"])          # never even reported
        # Claude pushes live edits by label
        got = live.set_fields({"Do you currently reside in the U.S.? *": "Yes", "Have you built a backend application? *": "Yes",
                               "Why Acme? *": "Because of the mission."})
        assert len(got["queued"]) == 3, got
        page.evaluate("window.__applybotPoll()")
        page.wait_for_function("document.querySelector('#why').value !== ''")
        assert page.eval_on_selector("#st", "e => e.options[e.selectedIndex].text") == "Yes"
        assert page.is_checked("input[name=be][value=y]")
        # the user types one answer by hand, then submits
        page.fill("#why", "I like building tools.")
        page.click("#go")
        page.evaluate("window.__applybotPoll()")
        page.wait_for_function("document.querySelector('#applybot-live-panel') && /Applied/.test(document.querySelector('#applybot-live-panel').shadowRoot.textContent)")
        browser.close()
    assert t["db"].get_job(t["job"]["id"])["status"] == "applied"


SIMPLE = """<!doctype html><html><body><form onsubmit="return false">
 <label for="fn">First Name *</label><input id="fn" required>
 <label for="em">Email *</label><input id="em" type="email" required>
 <button type="button" id="go" onclick="document.body.innerHTML='<h1>Thank you for applying!</h1>'">Submit application</button>
</form></body></html>"""


def _run_page(live, html, until):
    pw = pytest.importorskip("playwright.sync_api")

    def send(msg):
        kind, data = msg["type"], msg.get("data", {})
        if kind == "commands":
            return live.take_commands("1")
        if kind == "file":
            return {"ok": False}
        return getattr(live, kind)("1", data)

    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"no browser: {e}")
        page = browser.new_page()
        page.route(URL, lambda r: r.fulfill(body=html, content_type="text/html"))
        page.goto(URL)
        page.expose_function("__applybotSend", send)
        page.add_script_tag(path=str(EXT / "content.js"))
        page.wait_for_function("window.__applybotReady === true")
        out = page.evaluate(until)
        browser.close()
        return out


def test_auto_submit_only_when_complete(live):
    live.auto_submit = True
    poll_until_applied = """async () => { for (let i = 0; i < 40; i++) { await new Promise(r => setTimeout(r, 250));
        await window.__applybotPoll(); if (/Thank you/.test(document.body.innerText)) return true; } return false; }"""
    assert _run_page(live, SIMPLE, poll_until_applied) is True
    assert live.test["db"].get_job(live.test["job"]["id"])["status"] == "applied"


def test_auto_submit_waits_for_missing_answers_and_captcha(live):
    live.auto_submit = True
    wait = "async () => { await new Promise(r => setTimeout(r, 7000)); return document.querySelector('#go') !== null; }"
    assert _run_page(live, FORM, wait) is True                       # a required answer is missing: no submit
    captcha = SIMPLE.replace("<form", '<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe><form')
    assert _run_page(live, captcha, wait) is True                   # bot check on the page: no submit


def test_passive_recaptcha_badge_does_not_block_auto_submit(live):
    live.auto_submit = True
    badge = SIMPLE.replace("<form", '<div class="grecaptcha-badge"><iframe src="https://www.google.com/recaptcha/api2/'
                                    'anchor?size=invisible"></iframe></div><form')
    poll = """async () => { for (let i = 0; i < 40; i++) { await new Promise(r => setTimeout(r, 250));
        await window.__applybotPoll(); if (/Thank you/.test(document.body.innerText)) return true; } return false; }"""
    assert _run_page(live, badge, poll) is True


def test_add_jobs_appends_without_reopening(live):
    t = live.test
    live.open_jobs([t["job"]["id"]])
    live.page("7", {"url": URL, "fields": fields()})
    out = live.add_jobs([t["next"].id, t["next"].id])
    assert out == {"queued": 1, "opened": None} and t["opened"] == [URL]
    live.queue = ["a", "b"]
    live.add_jobs(["c", "a"], front=True)
    assert live.queue == ["c", "a", "b"]


def test_project_links_fill_portfolio_questions(live, profile):
    live.save_project_links(["https://arthurjclack.github.io", "https://github.com/ArthurJClack", "https://shitboxrally.example"])
    data = [{"key": "p1", "kind": "textarea", "label": "Optional GitHub, Project, or other links"},
            {"key": "p2", "kind": "text", "label": "Portfolio URL"}]
    fill = {x["key"]: x["value"] for x in live.page("7", {"url": URL, "fields": data})["fill"]}
    assert fill["p1"].splitlines()[-1] == "https://shitboxrally.example"
    assert fill["p2"].count(", ") == 2


def test_dashboard_feed_and_controls(live):
    port = live.start(0)
    t = live.test
    live.open_jobs([t["job"]["id"], t["next"].id])
    live.page("7", {"url": URL, "fields": fields()})
    html = urllib.request.urlopen(f"http://127.0.0.1:{port}/live/").read().decode()
    assert "ApplyBot Live" in html
    code, feed = _req(port, "/live/feed")
    assert code == 200 and feed["current"]["job"]["company"] == "Acme" and feed["queued"] == 1
    assert all(f["kind"] != "password" for f in feed["current"]["fields"])
    own = {"X-ApplyBot": "1", "Origin": f"http://127.0.0.1:{port}"}
    assert _req(port, "/live/control", {"action": "pause"}, own)[1] == {"auto_submit": False}
    assert _req(port, "/live/control", {"action": "skip"}, {"X-ApplyBot": "1", "Origin": "https://evil.example"})[0] == 403
    code, out = _req(port, "/live/control", {"action": "skip"}, own)
    assert code == 200 and out["next"].startswith("https://jobs.lever.co/beta/")
    assert live.take_commands("7")["commands"][0]["goto"] == out["next"]


ASHBY = """<!doctype html><html><body><form onsubmit="return false">
 <div class="ashby-application-form-field-entry">
   <label class="_required_x ashby-application-form-question-title" for="loc">Where are you located?</label>
   <input id="loc" placeholder="Start typing..." type="text"></div>
 <div class="ashby-application-form-field-entry">
   <label class="_required_x ashby-application-form-question-title">Do you reside in the U.S.?</label>
   <div class="ashby-application-form-input-yesno">
     <button type="button" aria-pressed="false" onclick="this.setAttribute('aria-pressed','true')">Yes</button>
     <button type="button" aria-pressed="false" onclick="this.setAttribute('aria-pressed','true')">No</button>
     <input type="checkbox" style="display:none"></div></div>
 <div class="ashby-application-form-field-entry">
   <label class="ashby-application-form-question-title">Export control status</label>
   <label><input type="radio" name="ec" value="a"> I am a U.S. person</label>
   <label><input type="radio" name="ec" value="b"> None of the above</label></div>
</form></body></html>"""


def test_ashby_titles_required_and_yes_no_buttons(live):
    got = _run_page(live, ASHBY, "() => 1")
    assert got == 1
    page = live.current()
    by = {f["label"]: f for f in page["fields"]}
    assert set(by) == {"Where are you located?", "Do you reside in the U.S.?", "Export control status"}
    assert by["Do you reside in the U.S.?"]["kind"] == "radio" and by["Do you reside in the U.S.?"]["required"]
    assert by["Export control status"]["options"] == ["I am a U.S. person", "None of the above"]
    assert by["Where are you located?"]["required"]
