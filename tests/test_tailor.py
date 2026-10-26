from applybot.tailor import apply_ai_plan, heuristic_tailor, safe_bullets, tailor_resume, template_cover_letter
from conftest import FakeLLM


def test_ai_plan_cannot_fabricate(profile):
    plan = {
        "summary": "Engineer with 10 years of experience",  # invented number -> dropped
        "experience": [
            {"ref": 1, "bullets": ["Trained PyTorch models on a 4-GPU cluster"]},
            {"ref": 0, "bullets": ["Built a FastAPI service handling 2M events per day",
                                   "Led a team of 15 engineers"]},  # 15 not in source -> replaced
            {"ref": 7, "bullets": ["ghost job"]},  # invalid ref ignored
        ],
        "projects": [{"ref": 0, "bullets": ["Built StudyBuddy for 1,200 students"]}],
        "skills": [{"category": "Languages", "items": ["Python", "Rust", "C++"]}],  # Rust is not in profile
    }
    r = apply_ai_plan(profile, plan)
    assert r["summary"] == profile["summary"]
    # metadata comes from profile and chronological order is preserved
    assert [e["company"] for e in r["experience"]] == ["Acme Analytics", "UT Machine Learning Lab"]
    assert r["experience"][0]["dates"] == "May 2026 - Aug 2026"
    acme = r["experience"][0]["bullets"]
    assert "Built a FastAPI service handling 2M events per day" in acme
    assert not any("15" in b for b in acme)
    assert r["skills"] == [{"category": "Languages", "items": ["Python", "C++"]}]
    assert len(r["projects"]) == 1 and r["projects"][0]["name"] == "StudyBuddy"
    assert r["contact"]["email"] == "alex.rivera@example.com"


def test_safe_bullets_keeps_originals_when_empty(profile):
    entry = profile["experience"][0]
    assert safe_bullets([], entry) == entry["bullets"]


def test_heuristic_orders_by_relevance(profile, job):
    r = heuristic_tailor(profile, job, max_bullets=2)
    assert len(r["experience"][0]["bullets"]) == 2
    assert any("Redis" in b or "FastAPI" in b for b in r["experience"][0]["bullets"])
    assert r["skills"][0]["items"][0] in ("Python", "SQL", "FastAPI", "PostgreSQL", "Redis", "Docker", "AWS")


def test_tailor_falls_back_without_ai(profile, job):
    class Off:
        available = False
    resume, method = tailor_resume(profile, job, Off())
    assert method == "heuristic" and resume["experience"]


def test_tailor_with_ai(profile, job):
    llm = FakeLLM(lambda p: {"summary": "Backend-focused CS student.",
                             "experience": [{"ref": 0, "bullets": ["Added Redis caching to the dashboard API"]}],
                             "skills": [{"category": "Backend", "items": ["Python", "Redis"]}]})
    resume, method = tailor_resume(profile, job, llm)
    assert method == "ai"
    assert resume["summary"] == "Backend-focused CS student."
    assert "Widgets Inc" in llm.prompts[0]


def test_template_cover_letter(profile, job):
    text = template_cover_letter(profile, job)
    assert "Widgets Inc" in text and "Alex Rivera" in text and "Backend Software Engineer Intern" in text
