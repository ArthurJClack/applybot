from datetime import datetime, timedelta, timezone

from applybot.db import DB
from applybot.matcher import hard_rejection, keyword_score, passes_filters, score_jobs
from applybot.models import Job
from conftest import FakeLLM

SEARCH = {"keywords": ["software engineer", "intern"], "exclude_keywords": ["senior", "staff"],
          "locations": ["New York"], "remote_ok": True, "max_age_days": 30}


def mk(**kw):
    base = dict(source="t", external_id="1", company="C", title="Software Engineer Intern", url="u",
                location="New York, NY", posted_at=datetime.now(timezone.utc).isoformat())
    base.update(kw)
    return Job(**base)


def test_filters():
    assert passes_filters(mk(), SEARCH)[0]
    assert passes_filters(mk(title="Software Engineering Internship"), SEARCH)[0]  # plural/suffix ok
    assert not passes_filters(mk(title="Senior Software Engineer"), SEARCH)[0]
    assert not passes_filters(mk(title="Internal Auditor"), SEARCH)[0]  # 'intern' word boundary
    assert not passes_filters(mk(location="Austin, TX"), SEARCH)[0]
    assert passes_filters(mk(location="Austin, TX", remote=True), SEARCH)[0]
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    assert not passes_filters(mk(posted_at=old), SEARCH)[0]


def test_keyword_score_prefers_relevant(profile, job):
    good, _ = keyword_score(job, profile)
    bad, _ = keyword_score({**job, "title": "Registered Nurse", "description": "Patient care, nursing license"},
                           profile)
    assert good > bad
    assert good >= 60


def test_sponsorship_hard_rejection(profile, job):
    assert hard_rejection({**job, "extra": {"sponsorship": "U.S. Citizenship is Required"}}, profile) == ""
    profile["preferences"]["Needs Sponsorship"] = "Yes"
    assert hard_rejection({**job, "extra": {"sponsorship": "U.S. Citizenship is Required"}}, profile)


def test_score_jobs_with_ai_and_dedupe(tmp_path, profile):
    db = DB(tmp_path / "t.db")
    assert db.upsert_job(mk(external_id="1"))
    assert not db.upsert_job(mk(external_id="2"))  # same company/title/location -> duplicate
    assert db.upsert_job(mk(external_id="3", title="Data Engineer Intern"))
    llm = FakeLLM(lambda p: {"score": 85 if "Title: Software Engineer Intern" in p else 40, "reason": "r",
                             "missing": ["x"]})
    cfg = {"matching": {"use_ai": True, "min_score": 60}}
    assert score_jobs(db, profile, llm, cfg, log=lambda *_: None) == 2
    assert [j["title"] for j in db.list_jobs(status="matched")] == ["Software Engineer Intern"]
    assert db.list_jobs(status="rejected")[0]["score"] == 40


def test_location_is_whole_word():
    search = {"keywords": ["intern"], "locations": ["WA"], "remote_ok": True}
    assert passes_filters({"title": "SWE Intern", "location": "Seattle, WA"}, search)[0]
    for loc in ("Ottawa, ON, Canada", "Milwaukee, WI", "Fort Wayne, IN"):
        assert not passes_filters({"title": "SWE Intern", "location": loc}, search)[0], loc
    assert not passes_filters({"title": "SWE Intern", "location": "Remote in Canada", "remote": True}, search)[0]
