from applybot.profile import all_skills, has_structured_sections, load_profile, split_name
from conftest import TEMPLATE_PROFILE, FakeLLM


def test_structured_parse(profile):
    c = profile["contact"]
    assert c["name"] == "Alex Rivera"
    assert c["email"] == "alex.rivera@example.com"
    assert c["github"] == "github.com/alexrivera"
    edu = profile["education"][0]
    assert edu["school"] == "University of Texas at Austin"
    assert edu["degree"] == "B.S. Computer Science"
    assert edu["gpa"] == "3.8"
    assert edu["dates"] == "Aug 2024 - May 2028"
    assert len(edu["details"]) == 2
    exp = profile["experience"]
    assert [e["company"] for e in exp] == ["Acme Analytics", "UT Machine Learning Lab"]
    assert exp[0]["title"] == "Software Engineering Intern"
    assert exp[0]["location"] == "Austin, TX"
    assert exp[0]["dates"] == "May 2026 - Aug 2026"
    assert len(exp[0]["bullets"]) == 3
    assert profile["projects"][0]["link"] == "github.com/alexrivera/studybuddy"
    assert profile["projects"][0]["tech"] == "React, TypeScript, Node.js, MongoDB"
    assert profile["leadership"][0]["company"] == "Longhorn Developers Club"
    assert profile["preferences"]["Needs Sponsorship"] == "No"
    assert "Python" in all_skills(profile) and "MongoDB" in all_skills(profile)
    assert split_name(profile) == ("Alex", "Rivera")


def test_freeform_uses_ai_and_caches(tmp_path):
    f = tmp_path / "me.txt"
    f.write_text("I'm Jo Smith, jo@x.com. I interned at Foo Corp in 2025 writing Go.", encoding="utf-8")
    assert not has_structured_sections(f.read_text())
    llm = FakeLLM(lambda p: {"contact": {"name": "Jo Smith", "email": "jo@x.com"},
                             "experience": [{"title": "Intern", "company": "Foo Corp", "dates": "2025",
                                             "bullets": ["Wrote Go"]}],
                             "skills": [{"category": "Languages", "items": ["Go"]}]})
    cache = tmp_path / "cache.json"
    p = load_profile(f, llm, "auto", cache)
    assert p["contact"]["name"] == "Jo Smith" and p["experience"][0]["company"] == "Foo Corp"
    assert p["contact"]["phone"] == ""  # schema defaults preserved
    load_profile(f, llm, "auto", cache)
    assert len(llm.prompts) == 1  # second load served from cache


def test_template_detected_as_structured():
    assert has_structured_sections(TEMPLATE_PROFILE)
