from applybot.answers import AnswerBank
from applybot.db import DB
from applybot.llm import LLM
from applybot.matcher import passes_filters, prune_unwanted
from applybot.models import Job
from applybot.sources.ashby import company_name, is_remote_posting
from applybot.sources.ats import ats_key, dedupe_key

WA = {"keywords": ["software engineer"], "locations": ["Seattle", "WA", "Washington"], "remote_ok": True}


def mk(**kw):
    base = dict(source="t", external_id="1", company="C", title="Software Engineer", url="u", location="Seattle, WA")
    base.update(kw)
    return Job(**base)


def test_washington_state_not_dc():
    assert passes_filters(mk(location="Seattle, WA"), WA)[0]
    assert passes_filters(mk(location="Spokane, Washington"), WA)[0]
    assert not passes_filters(mk(location="Washington, DC"), WA)[0]
    assert not passes_filters(mk(location="Washington D.C."), WA)[0]
    assert not passes_filters(mk(location="Ottawa, ON, Canada"), WA)[0]


def test_foreign_remote_blocked():
    assert passes_filters(mk(location="Remote in USA", remote=True), WA)[0]
    assert passes_filters(mk(location="Remote in USA; Santa Clara, CA", remote=True), WA)[0]
    assert not passes_filters(mk(location="London, UK; Remote in UK", remote=True), WA)[0]
    assert not passes_filters(mk(location="Remote in Canada", remote=True), WA)[0]
    assert passes_filters(mk(location="Remote in Canada", remote=True), {**WA, "locations": ["Canada"]})[0]


def test_ashby_remote_and_name():
    assert not is_remote_posting({"isRemote": True, "workplaceType": "OnSite"}, "San Francisco")
    assert is_remote_posting({"workplaceType": "Remote"}, "United States")
    assert company_name("openai") == "OpenAI"
    assert company_name("acme-robotics") == "Acme Robotics"


def test_ats_key_parsing():
    assert ats_key("https://job-boards.greenhouse.io/stripe/jobs/8128744") == ("greenhouse", "stripe", "8128744", "")
    assert ats_key("https://stripe.com/jobs/search?gh_jid=8128744")[:3] == ("greenhouse", "stripe", "8128744")
    assert ats_key("https://jobs.eu.lever.co/acme/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b/apply")[0::3] == ("lever", "eu")
    assert ats_key("https://jobs.ashbyhq.com/ramp/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b")[0] == "ashby"
    assert ats_key("https://example.com/careers/123") is None


def test_cross_source_dedupe(tmp_path):
    db = DB(tmp_path / "t.db")
    gh = mk(source="greenhouse", external_id="stripe:1", company="Stripe",
            apply_url="https://job-boards.greenhouse.io/stripe/jobs/1")
    simp = mk(source="simplify", external_id="99", company="Stripe Inc", location="Seattle",
              url="https://stripe.com/jobs/search?gh_jid=1", apply_url="https://job-boards.greenhouse.io/stripe/jobs/1")
    assert db.upsert_job(gh)
    assert not db.upsert_job(simp)


def test_prune_unwanted(tmp_path):
    db = DB(tmp_path / "t.db")
    db.upsert_job(mk(external_id="a", location="Seattle, WA"))
    db.upsert_job(mk(external_id="b", title="Software Engineer II", location="Toronto, ON, Canada"))
    assert prune_unwanted(db, WA) == 1
    assert db.status_counts() == {"new": 1, "skipped": 1}


def test_ai_reason():
    assert "ANTHROPIC_API_KEY" in LLM({"provider": "anthropic", "api_key": ""}).unavailable_reason()
    assert LLM({"provider": "anthropic", "api_key": "x"}).unavailable_reason() == ""


def test_answers_save_keeps_header(tmp_path, profile):
    p = tmp_path / "answers.yaml"
    p.write_text("# my notes\n# keep me\nbasics:\n  city: Seattle\n", encoding="utf-8")
    bank = AnswerBank(p, profile)
    bank.save()
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# my notes\n# keep me\n")
    assert "city: Seattle" in text


# ---------------------------------------------------------------- 2026-10-15 improvements
from applybot.cli import _schtasks_args, _schedule_run_command, SCHEDULE_TASK_NAME
from applybot.db import SUBMITTED, STATUSES
from applybot.pipeline import over_company_cap


def test_new_lifecycle_statuses():
    for st in ("interviewing", "offer", "rejected_by_company"):
        assert st in STATUSES and st in SUBMITTED


def test_company_app_counts_and_cap(tmp_path):
    db = DB(tmp_path / "t.db")
    for i, company in enumerate(["Stripe", "stripe", "Ramp", "Stripe"]):
        db.upsert_job(mk(external_id=str(i), company=company, title=f"SWE {i}"))
    rows = db.conn.execute("SELECT id, company FROM jobs ORDER BY created_at, rowid").fetchall()
    for row, status in zip(rows, ["applied", "interviewing", "applied", "matched"]):
        db.update_job(row["id"], status=status)
    counts = db.company_app_counts()
    assert counts == {"stripe": 2, "ramp": 1}
    assert over_company_cap(counts, "stripe", 2)
    assert not over_company_cap(counts, "ramp", 2)
    assert not over_company_cap(counts, "stripe", 0)  # 0 = unlimited
    assert not over_company_cap(counts, "", 2)


def test_export_csv(tmp_path):
    db = DB(tmp_path / "t.db")
    db.upsert_job(mk(external_id="x", company="Acme", title="SWE, Platform"))
    db.log_application("abc", "https://x", "applied", "review", notes="ok")
    paths = db.export_csv(tmp_path / "out")
    jobs_csv = (tmp_path / "out" / "jobs.csv").read_text(encoding="utf-8-sig")
    apps_csv = (tmp_path / "out" / "applications.csv").read_text(encoding="utf-8-sig")
    assert len(paths) == 2 and "SWE, Platform" in jobs_csv and jobs_csv.startswith("id,")
    assert "applied" in apps_csv


def test_schedule_command_shape(tmp_path):
    args = _schtasks_args("create", "08:45", 'py main.py refresh')
    assert args[:4] == ["schtasks", "/Create", "/TN", SCHEDULE_TASK_NAME]
    assert "/SC" in args and "DAILY" in args and "08:45" in args
    assert _schtasks_args("delete")[1] == "/Delete"
    cmd = _schedule_run_command(str(tmp_path / "config.yaml"))
    assert "refresh" in cmd and str(tmp_path) in cmd
