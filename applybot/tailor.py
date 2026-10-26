"""Tailor the candidate's resume and cover letter to a specific posting.

Truthfulness guarantees (enforced in code, not just in the prompt):
  * The AI only chooses *which* existing entries/bullets to show and how to phrase them; employers, titles,
    schools, degrees and dates are always copied from the profile, never from AI output.
  * Any bullet containing a number that is not present in the original entry is replaced by an original bullet.
  * Skills that do not appear anywhere in the profile are dropped.
"""
from __future__ import annotations

import copy
import json
import re
from collections import Counter

import httpx
from bs4 import BeautifulSoup

from applybot.llm import LLM, LLMError
from applybot.profile import all_skills, profile_to_text, short_term_hit
from applybot.sources import USER_AGENT

STOPWORDS = set("""a an the and or of to in for on with at by from as is are be been being this that these those it its
you your we our they their he she will would can could should may might must not no yes all any each more most other
some such than too very just about into over under again further then once here there when where why how who whom
which what while during before after above below up down out off own same so only both few nor also etc using use
work working team teams role job position candidate candidates experience years year strong ability including
including within across new well per via""".split())

NUM_RE = re.compile(r"\d[\d,.]*\s*%?|\$\s*\d[\d,.]*[kKmMbB]?")


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z0-9+#.\-]*[a-z0-9+#]|[a-z]", (text or "").lower()) if t not in STOPWORDS]


def job_keywords(job: dict, top: int = 60) -> list[str]:
    counts = Counter(tokens(job.get("title", "")) * 3 + tokens(job.get("description", "")))
    return [w for w, _ in counts.most_common(top)]


def relevance(text: str, kw: set[str]) -> int:
    return sum(1 for t in set(tokens(text)) if t in kw)


def fetch_description(url: str, timeout: float = 30, *more_urls: str) -> str:
    """Posting text for sources without descriptions: the ATS API when the link is Greenhouse/Lever/Ashby,
    otherwise a best-effort plain-text scrape of the page."""
    from applybot.sources.ats import ats_description
    desc = ats_description(url, *more_urls)
    if desc:
        return desc[:15000]
    if not url:
        return ""
    try:
        r = httpx.get(url, follow_redirects=True, timeout=timeout, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
    except httpx.HTTPError:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]
    return "\n".join(lines)[:15000]


# ---------------------------------------------------------------------- guard rails
def _numbers(text: str) -> set[str]:
    return {re.sub(r"[\s,]", "", m.group(0)).rstrip(".") for m in NUM_RE.finditer(text or "")}


def _best_original(bullet: str, originals: list[str]) -> str:
    bt = set(tokens(bullet))
    return max(originals, key=lambda o: len(bt & set(tokens(o))), default="")


def safe_bullets(new: list[str], entry: dict) -> list[str]:
    originals = list(entry.get("bullets") or entry.get("details") or [])
    allowed = _numbers(json.dumps(entry, ensure_ascii=False))
    out: list[str] = []
    for b in new or []:
        if not isinstance(b, str) or not b.strip():
            continue
        b = b.strip().lstrip("-*\u2022 ").strip()
        if _numbers(b) - allowed:
            b = _best_original(b, originals) or ""
        if b and b not in out:
            out.append(b)
    return out or originals


def safe_skills(groups, profile: dict) -> list[dict]:
    known = {s.lower() for s in all_skills(profile)}
    raw = (profile.get("raw") or json.dumps(profile)).lower()
    out = []
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        items = [i for i in g.get("items", []) if isinstance(i, str) and (
            i.lower() in known or re.search(r"(?<![a-z0-9])" + re.escape(i.lower()) + r"(?![a-z0-9+#])", raw))]
        if items:
            out.append({"category": g.get("category") or "Skills", "items": items})
    return out or copy.deepcopy(profile.get("skills", []))


# ---------------------------------------------------------------------- tailoring
def heuristic_tailor(profile: dict, job: dict, max_bullets: int = 5, max_projects: int = 3) -> dict:
    kw = set(job_keywords(job))
    r = base_resume(profile)
    for section in ("experience", "leadership"):
        for e in r[section]:
            e["bullets"] = sorted(e.get("bullets", []), key=lambda b: -relevance(b, kw))[:max_bullets]
    projects = sorted(r["projects"], key=lambda p: -relevance(json.dumps(p), kw))
    r["projects"] = projects[:max_projects]
    for p in r["projects"]:
        p["bullets"] = sorted(p.get("bullets", []), key=lambda b: -relevance(b, kw))[:max_bullets]
    for g in r["skills"]:
        g["items"] = sorted(g["items"], key=lambda s: -relevance(s, kw))
    r["skills"].sort(key=lambda g: -sum(relevance(s, kw) for s in g["items"]))
    return r


def base_resume(profile: dict) -> dict:
    keys = ("contact", "summary", "education", "experience", "projects", "leadership", "skills",
            "certifications", "awards")
    defaults = {"contact": {}, "summary": ""}
    return {k: copy.deepcopy(profile.get(k) or defaults.get(k, [])) for k in keys}


TAILOR_PROMPT = """Tailor this candidate's resume to the job posting below so it fits on ONE page.

STRICT RULES - violating these is unacceptable:
1. Use ONLY facts present in the candidate data. Never invent employers, titles, dates, metrics, numbers,
   technologies, responsibilities, or outcomes. Do not inflate scope or seniority.
2. You MAY: pick the most relevant entries and bullets, reorder them, rephrase bullets to use the posting's
   terminology where it truthfully applies, merge/trim bullets, and write a 1-2 sentence summary.
3. Refer to entries by their zero-based index ("ref") in the candidate arrays. Omit irrelevant entries.
4. Skills must be copied from the candidate's skills/technologies; order the most relevant first.
5. At most {max_bullets} bullets per entry, each under ~30 words, starting with a strong action verb.

Return JSON:
{{
  "summary": "<1-2 sentences, or empty string>",
  "experience": [{{"ref": <int>, "bullets": ["..."]}}],
  "projects": [{{"ref": <int>, "bullets": ["..."]}}],
  "leadership": [{{"ref": <int>, "bullets": ["..."]}}],
  "skills": [{{"category": "...", "items": ["..."]}}]
}}

CANDIDATE (JSON):
{profile}

JOB POSTING:
Company: {company}
Title: {title}
Location: {location}
Description:
{description}"""


def ai_tailor(profile: dict, job: dict, llm: LLM, max_bullets: int = 5) -> dict:
    data = llm.complete_json(TAILOR_PROMPT.format(
        max_bullets=max_bullets, profile=profile_to_text(profile)[:14000], company=job.get("company", ""),
        title=job.get("title", ""), location=job.get("location", ""),
        description=(job.get("description") or "(not available)")[:8000]),
        system="You are an expert, scrupulously honest resume writer.")
    return apply_ai_plan(profile, data, max_bullets)


def apply_ai_plan(profile: dict, data: dict, max_bullets: int = 5) -> dict:
    """Merge an AI tailoring plan into a resume while enforcing the truthfulness guarantees."""
    r = base_resume(profile)
    if not isinstance(data, dict):
        return r
    for section in ("experience", "projects", "leadership"):
        originals = profile.get(section) or []
        plan = data.get(section)
        if not isinstance(plan, list):
            continue
        chosen: list[tuple[int, dict]] = []
        used: set[int] = set()
        for item in plan:
            try:
                ref = int(item.get("ref"))
            except (TypeError, ValueError, AttributeError):
                continue
            if not 0 <= ref < len(originals) or ref in used:
                continue
            used.add(ref)
            entry = copy.deepcopy(originals[ref])
            entry["bullets"] = safe_bullets(item.get("bullets"), originals[ref])[:max_bullets]
            chosen.append((ref, entry))
        if section == "experience":
            chosen.sort(key=lambda pair: pair[0])  # keep the profile's (chronological) order
            if not chosen:  # never drop work experience entirely
                chosen = list(enumerate(copy.deepcopy(originals)))
        r[section] = [e for _, e in chosen]
    summary = data.get("summary") or ""
    if isinstance(summary, str) and not (_numbers(summary) - _numbers(json.dumps(profile, ensure_ascii=False))):
        r["summary"] = summary.strip()
    r["skills"] = safe_skills(data.get("skills"), profile)
    return r


def _in_text(term: str, text_lower: str, text_orig: str) -> bool:
    """Whole-term match. Very short skills (Go, R, C) must match case-sensitively so plain words don't count."""
    if len(term) <= 2:
        return short_term_hit(term, text_orig)
    return re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9+#])", text_lower) is not None


def boost_skills(resume: dict, profile: dict, job: dict) -> dict:
    """Make sure skills the posting names AND the candidate really has are listed in the Skills section.

    ATS keyword filters match on literal terms, and a rewrite can drop a relevant skill. Only skills already in
    the profile are ever added, so this stays truthful."""
    orig = f"{job.get('title', '')}\n{job.get('description', '')}"
    low = orig.lower()
    if not low.strip():
        return resume
    groups = resume.setdefault("skills", [])
    have = {i.lower() for g in groups for i in g.get("items", [])}
    for pg in profile.get("skills") or []:
        cat = pg.get("category") or "Skills"
        for item in pg.get("items") or []:
            if not isinstance(item, str) or item.lower() in have or not _in_text(item, low, orig):
                continue
            target = next((g for g in groups if (g.get("category") or "").lower() == cat.lower()), None)
            if target is None:
                target = {"category": cat, "items": []}
                groups.append(target)
            target["items"].insert(0, item)
            have.add(item.lower())
    return resume


def keyword_report(resume: dict, profile: dict, job: dict, top: int = 30) -> dict:
    """How well the resume echoes the posting's most important terms (what an ATS keyword filter looks at).

    covered   - posting terms that appear in the resume
    available - terms the candidate's profile mentions but the resume leaves out (safe to add if true)
    missing   - posting terms that appear nowhere in the profile (genuine gaps - do not fake these)"""
    kws = [k for k in job_keywords(job, top=top * 2) if len(k) > 2 and not k.isdigit()][:top]
    resume_terms = set(tokens(json.dumps(resume, ensure_ascii=False)))
    profile_terms = set(tokens(profile_to_text(profile)))
    covered = [k for k in kws if k in resume_terms]
    available = [k for k in kws if k not in resume_terms and k in profile_terms]
    missing = [k for k in kws if k not in resume_terms and k not in profile_terms]
    return {"considered": len(kws), "coverage": round(100 * len(covered) / len(kws)) if kws else 0,
            "covered": covered, "available": available, "missing": missing}


def format_report(r: dict) -> str:
    if not r["considered"]:
        return "No posting description was available, so keyword coverage could not be checked.\n"
    return (f"ATS keyword coverage: {r['coverage']}% of the posting's top {r['considered']} terms appear in this "
            f"resume.\n\nIn the resume: {', '.join(r['covered']) or '-'}\n\n"
            f"In your profile but NOT on this resume (add to your profile bullets if they are true): "
            f"{', '.join(r['available']) or '-'}\n\n"
            f"Not in your profile at all (real gaps - don't claim them): {', '.join(r['missing']) or '-'}\n")


def tailor_resume(profile: dict, job: dict, llm: LLM | None, max_bullets: int = 5) -> tuple[dict, str]:
    """Returns (resume, method) where method is 'ai' or 'heuristic'."""
    if llm is not None and llm.available:
        try:
            return boost_skills(ai_tailor(profile, job, llm, max_bullets), profile, job), "ai"
        except LLMError:
            pass
    return boost_skills(heuristic_tailor(profile, job, max_bullets), profile, job), "heuristic"


COVER_PROMPT = """Write a concise, specific cover letter (220-320 words) for this application.
Only cite experience, skills, and achievements that appear in the candidate data - never invent anything.
Connect 2-3 of the candidate's most relevant real experiences to the role's needs. Professional, warm, no cliches,
no placeholders like [Company]. Plain text only: greeting, 3-4 short paragraphs, sign-off with the candidate's name.

CANDIDATE:
{profile}

POSTING:
Company: {company}
Title: {title}
Description:
{description}"""


def cover_letter(profile: dict, job: dict, llm: LLM | None) -> str:
    if llm is not None and llm.available:
        try:
            text = llm.complete(COVER_PROMPT.format(
                profile=profile_to_text(profile)[:10000], company=job.get("company", ""),
                title=job.get("title", ""), description=(job.get("description") or "")[:6000]),
                system="You are an expert career coach who writes honest, compelling cover letters.",
                max_tokens=1200)
            if text.strip():
                return text.strip()
        except LLMError:
            pass
    return template_cover_letter(profile, job)


def template_cover_letter(profile: dict, job: dict) -> str:
    name = profile.get("contact", {}).get("name", "")
    kw = set(job_keywords(job))
    bullets = [(b, e) for e in profile.get("experience", []) + profile.get("projects", [])
               for b in e.get("bullets", [])]
    top = sorted(bullets, key=lambda be: -relevance(be[0], kw))[:2]
    skills = sorted(all_skills(profile), key=lambda s: -relevance(s, kw))[:5]
    edu = (profile.get("education") or [{}])[0]
    lines = [f"Dear {job.get('company') or 'Hiring'} Team,", "",
             f"I am excited to apply for the {job.get('title', 'open')} position at {job.get('company', 'your company')}."
             + (f" I am currently pursuing a {edu.get('degree')} at {edu.get('school')}." if edu.get("school") else ""),
             ""]
    if top:
        lines.append("A few experiences that I believe are relevant:")
        for b, e in top:
            where = e.get("company") or e.get("name") or ""
            lines.append(f"  - {b}" + (f" ({where})" if where else ""))
        lines.append("")
    if skills:
        lines += [f"I bring hands-on experience with {', '.join(skills)}, and I am eager to apply these skills "
                  f"to the challenges your team is working on.", ""]
    lines += ["Thank you for your time and consideration. I would welcome the opportunity to discuss how I can "
              "contribute.", "", "Sincerely,", name]
    return "\n".join(lines)
