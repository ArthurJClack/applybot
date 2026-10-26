"""Job discovery orchestration, filtering, and fit scoring (AI with keyword fallback)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Callable

from applybot.db import DB
from applybot.llm import LLM, LLMError
from applybot.models import Job
from applybot.profile import all_skills, profile_to_text, short_term_hit
from applybot.sources import make_client, registry


def _word_re(kw: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(s|es|ship|ships)?(?![a-z0-9])")


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# "Washington" (the state) must not match Washington, DC
_DC_RE = re.compile(r"washington,?\s*d\.?\s*c\.?(?![a-z])|district of columbia")
FOREIGN = ("canada", "uk", "united kingdom", "england", "scotland", "ireland", "india", "germany", "france",
           "netherlands", "spain", "poland", "romania", "europe", "emea", "apac", "latam", "australia",
           "new zealand", "singapore", "japan", "china", "mexico", "brazil", "argentina", "philippines",
           "pakistan", "israel", "switzerland", "sweden", "portugal", "italy", "korea", "taiwan")


def _has(term: str, text: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def location_hit(loc: str, locations: list[str]) -> bool:
    for l in locations:
        text = _DC_RE.sub(" ", loc) if l in ("washington", "washington state") else loc
        if l == "washington state":
            l = "washington"
        if _has(l, text):
            return True
    return False


def remote_ok_for(loc: str, remote: bool, locations: list[str]) -> bool:
    """A remote posting passes unless every remote option is in a country the user didn't ask for."""
    if not remote:
        return False
    parts = [p.strip() for p in re.split(r"[;|]", loc) if p.strip()]
    remote_parts = [p for p in parts if "remote" in p or "anywhere" in p] or parts or [""]
    wanted_foreign = {f for f in FOREIGN if any(_has(f, l) for l in locations)}
    for p in remote_parts:
        foreign = [f for f in FOREIGN if _has(f, p) and f not in wanted_foreign]
        if not foreign or re.search(r"\b(us|usa|u\.s\.a?\.?|united states|north america)\b", p):
            return True
    return False


def passes_filters(job: Job | dict, search: dict) -> tuple[bool, str]:
    get = (lambda k: job.get(k)) if isinstance(job, dict) else (lambda k: getattr(job, k))
    title = (get("title") or "").lower()
    keywords = [k for k in search.get("keywords") or [] if k]
    if keywords and not any(_word_re(k).search(title) for k in keywords):
        return False, "title does not match keywords"
    for k in search.get("required_keywords") or []:
        if not _word_re(k).search(title):
            return False, f"title missing required keyword '{k}'"
    for k in search.get("exclude_keywords") or []:
        if _word_re(k).search(title):
            return False, f"title contains excluded keyword '{k}'"
    locations = [l.lower() for l in search.get("locations") or []]
    if locations:
        loc = (get("location") or "").lower()
        if not (location_hit(loc, locations) or (search.get("remote_ok", True) and remote_ok_for(loc, get("remote"), locations))):
            return False, "location mismatch"
    max_age = search.get("max_age_days")
    posted = _parse_date(get("posted_at") or "")
    if max_age and posted and posted < datetime.now(timezone.utc) - timedelta(days=int(max_age)):
        return False, "posting too old"
    job_types = search.get("job_types")
    if job_types and get("job_type") and get("job_type") not in job_types:
        return False, f"job type {get('job_type')} not wanted"
    return True, ""


def discover(cfg: dict, db: DB, log: Callable[[str], None] = print, only: list[str] | None = None) -> dict:
    """Fetch postings from every enabled source, filter them, and store new ones."""
    search = cfg["search"]
    stats = {"fetched": 0, "kept": 0, "new": 0, "errors": {}}
    sources = registry()
    with make_client() as http:
        for name, scfg in (search.get("sources") or {}).items():
            if only and name not in only:
                continue
            if not (scfg or {}).get("enabled") or name not in sources:
                continue
            try:
                jobs = sources[name](scfg, search, http)
            except Exception as e:  # one broken source must not stop the others
                stats["errors"][name] = str(e)
                log(f"[red]{name}: {e}[/red]")
                continue
            kept = [j for j in jobs if passes_filters(j, search)[0]]
            kept.sort(key=lambda j: j.posted_at or "", reverse=True)  # newest first before capping
            kept = kept[: int(search.get("max_per_source", 500))]
            new = sum(db.upsert_job(j) for j in kept)
            stats["fetched"] += len(jobs)
            stats["kept"] += len(kept)
            stats["new"] += new
            log(f"{name}: fetched {len(jobs)}, matched filters {len(kept)}, new {new}")
    pruned = prune_unwanted(db, search)
    if pruned:
        stats["pruned"] = pruned
        log(f"skipped {pruned} older posting(s) that no longer match your filters")
    return stats


def prune_unwanted(db: DB, search: dict) -> int:
    """Mark still-unprocessed jobs that fail the *current* filters as skipped (e.g. after changing locations)."""
    n = 0
    for job in db.list_jobs(status="new", limit=100000, order="date"):
        ok, why = passes_filters(job, search)
        if not ok:
            db.update_job(job["id"], status="skipped", score_reason=f"filtered: {why}")
            n += 1
    return n


# ---------------------------------------------------------------------- scoring
SPONSOR_BLOCKERS = ("u.s. citizenship is required", "does not offer sponsorship", "no sponsorship")


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("yes", "true", "y", "1", "required")


def hard_rejection(job: dict, profile: dict) -> str:
    prefs = {k.lower(): v for k, v in (profile.get("preferences") or {}).items()}
    needs = next((v for k, v in prefs.items() if "sponsor" in k), None)
    if needs is not None and _truthy(needs):
        spons = str((job.get("extra") or {}).get("sponsorship", "")).lower()
        text = (job.get("description") or "").lower()
        if any(b in spons for b in SPONSOR_BLOCKERS) or "will not sponsor" in text or "unable to sponsor" in text:
            return "position does not sponsor work visas"
    return ""


def keyword_score(job: dict, profile: dict) -> tuple[float, str]:
    orig = f"{job.get('title', '')}\n{job.get('description', '')}"
    text = orig.lower()
    skills = all_skills(profile)

    def hit(s: str) -> bool:
        if len(s) <= 2:  # "Go", "R", "C": only count the capitalised form, not the English word/letter
            return short_term_hit(s, orig)
        return _word_re(s).search(text) is not None

    matched = [s for s in skills if s and hit(s)]
    prefs = {k.lower(): v for k, v in (profile.get("preferences") or {}).items()}
    desired = [r.strip() for r in re.split(r"[,;]", prefs.get("desired roles", "")) if r.strip()]
    title = (job.get("title") or "").lower()
    role_hit = any(all(w in title for w in norm_words(r)) for r in desired) if desired else True

    if job.get("description"):
        skill_part = min(1.0, len(matched) / 6) * 60
    else:
        skill_part = 35  # no description available: neutral
    score = skill_part + (40 if role_hit else 15)
    reason = f"matched skills: {', '.join(matched[:12]) or 'none'}; desired-role match: {role_hit}"
    return round(min(score, 100), 1), reason


def norm_words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9+#]+", s.lower()) if w not in ("and", "or", "the", "a")]


SCORE_PROMPT = """Rate how well this candidate fits this posting, from 0 to 100.
Consider: required skills/experience vs. what the candidate actually has, seniority/education level,
job type (internship vs full-time), location/remote, and work authorization/sponsorship constraints.
Be calibrated: 80+ = strong fit worth applying, 60-79 = reasonable, <50 = poor fit.

Return JSON: {{"score": <int>, "reason": "<one sentence>", "missing": ["<important requirement the candidate lacks>"]}}

CANDIDATE:
{profile}

POSTING:
Company: {company}
Title: {title}
Location: {location}  (remote: {remote})
Type: {job_type}
Extra: {extra}
Description:
{description}"""


def ai_score(job: dict, profile: dict, llm: LLM) -> tuple[float, str]:
    data = llm.complete_json(SCORE_PROMPT.format(
        profile=profile_to_text(profile, include_raw_other=False)[:6000],
        company=job.get("company"), title=job.get("title"), location=job.get("location"),
        remote=job.get("remote"), job_type=job.get("job_type"), extra=json.dumps(job.get("extra") or {}),
        description=(job.get("description") or "(not available - judge from title/company)")[:5000],
    ), system="You are an experienced technical recruiter.", max_tokens=1200)
    score = float(data.get("score", 0))
    reason = data.get("reason", "")
    if data.get("missing"):
        reason += " | missing: " + ", ".join(map(str, data["missing"][:5]))
    return max(0.0, min(100.0, score)), reason


def score_jobs(db: DB, profile: dict, llm: LLM, cfg: dict, limit: int = 100,
               log: Callable[[str], None] = print) -> int:
    from applybot.sources import make_client
    from applybot.sources.ats import ats_description

    use_ai = cfg["matching"].get("use_ai", True) and llm.available
    if not use_ai:
        log(f"[yellow]{llm.unavailable_reason() or 'AI scoring disabled in settings - using keyword scoring'}[/yellow]")
    min_score = float(cfg["matching"].get("min_score", 60))
    n = 0
    with make_client() as http:
        for job in db.list_jobs(status="new", unscored=True, limit=limit, order="date"):
            if not (job.get("description") or "").strip():
                desc = ats_description(job.get("url"), job.get("apply_url"), http=http)  # fast public APIs only
                if desc:
                    job["description"] = desc[:15000]
                    db.update_job(job["id"], description=job["description"])
            blocker = hard_rejection(job, profile)
            if blocker:
                db.update_job(job["id"], score=0, score_reason=blocker, status="rejected")
                continue
            try:
                score, reason = ai_score(job, profile, llm) if use_ai else keyword_score(job, profile)
            except LLMError as e:
                log(f"[yellow]AI scoring failed for {job['id']} ({e}); using keyword score[/yellow]")
                score, reason = keyword_score(job, profile)
            status = "matched" if score >= min_score else "rejected"
            db.update_job(job["id"], score=score, score_reason=reason, status=status)
            log(f"{score:5.1f}  {job['company']} - {job['title']}")
            n += 1
    return n
