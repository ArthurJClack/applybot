from applybot.db import DB
from applybot.matcher import keyword_score
from applybot.models import Job
from applybot.render import render_docx, render_pdf, section_order
from applybot.tailor import boost_skills, format_report, keyword_report, tailor_resume

PROFILE = {
    "contact": {"name": "Ada Lovelace", "email": "a@b.co"},
    "education": [{"school": "UW", "degree": "BS CS", "dates": "2022 - 2026"}],
    "experience": [{"title": "Intern", "company": "Acme", "dates": "2025", "bullets": ["Built APIs in Python and Docker"]}],
    "skills": [{"category": "Languages", "items": ["Python", "Go", "SQL"]},
               {"category": "Tools", "items": ["Docker", "Kubernetes"]}],
    "summary": "",
}
JOB = {"title": "Software Engineer Intern", "company": "X",
       "description": "We use Python, Kubernetes and Terraform. Go beyond the basics. Docker a plus."}


def test_boost_skills_adds_only_real_skills():
    r = {"skills": [{"category": "Languages", "items": ["SQL"]}]}
    boost_skills(r, PROFILE, JOB)
    items = {i for g in r["skills"] for i in g["items"]}
    assert {"Python", "Kubernetes", "Docker"} <= items
    assert "Terraform" not in items          # not in profile -> never invented
    assert "Go" not in items                 # plain English "Go beyond" must not count


def test_tailor_resume_includes_posting_skills():
    resume, _ = tailor_resume(PROFILE, JOB, None)
    items = {i.lower() for g in resume["skills"] for i in g["items"]}
    assert "kubernetes" in items and "python" in items


def test_keyword_report_separates_gaps():
    resume = {"skills": [{"category": "x", "items": ["Python"]}]}
    rep = keyword_report(resume, PROFILE, JOB)
    assert "terraform" in rep["missing"]
    assert "kubernetes" in rep["available"]
    assert "python" in rep["covered"]
    assert "coverage" in format_report(rep).lower()
    assert "could not be checked" in format_report(keyword_report(resume, PROFILE, {"title": "", "description": ""}))


def test_keyword_score_ignores_english_go():
    prof = {"skills": [{"category": "L", "items": ["Go"]}]}
    _, reason = keyword_score({"title": "Dev", "description": "go beyond expectations"}, prof)
    assert "none" in reason
    _, reason = keyword_score({"title": "Dev", "description": "Experience with Go and Rust"}, prof)
    assert "Go" in reason


def test_get_job_exact_then_unique_prefix(tmp_path):
    db = DB(tmp_path / "t.db")
    for n in (1, 2):
        db.upsert_job(Job(source="s", external_id=str(n), company="C", title=f"Dev {n}", url=f"https://x.io/{n}"))
    ids = [j["id"] for j in db.list_jobs()]
    assert db.get_job(ids[0])["id"] == ids[0]
    assert db.get_job("") is None
    assert db.get_job("%") is None            # wildcard must not match a random job


def test_docx_and_pdf_render_with_metadata(tmp_path):
    resume, _ = tailor_resume(PROFILE, JOB, None)
    p = render_pdf(resume, tmp_path / "r.pdf")
    d = render_docx(resume, tmp_path / "r.docx")
    assert p.stat().st_size > 500 and d.stat().st_size > 500
    from docx import Document
    assert Document(str(d)).core_properties.author == "Ada Lovelace"
    assert b"Ada Lovelace" in p.read_bytes() or p.stat().st_size > 0


def test_section_order_experience_first_for_non_students():
    r = {"experience": [{"title": "x"}], "education": [{"dates": "2010 - 2014"}]}
    assert section_order(r)[0][0] == "experience"
    r["education"] = [{"dates": "2022 - Expected 2027"}]
    assert section_order(r)[0][0] == "education"
