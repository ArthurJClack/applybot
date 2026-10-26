"""Ashby public job board API (no auth). `companies` are org slugs from jobs.ashbyhq.com/<slug>."""
from __future__ import annotations

import httpx

from applybot.models import Job
from applybot.sources import guess_job_type, html_to_text, is_remote


KNOWN_NAMES = {"openai": "OpenAI", "notion": "Notion", "ramp": "Ramp", "linear": "Linear", "deel": "Deel",
               "posthog": "PostHog", "elevenlabs": "ElevenLabs", "supabase": "Supabase", "vercel": "Vercel"}


def company_name(slug: str) -> str:
    """Ashby's board API only gives the slug; make it presentable for resumes, folders and cover letters."""
    s = slug.lower()
    if s in KNOWN_NAMES:
        return KNOWN_NAMES[s]
    return " ".join(w.capitalize() for w in slug.replace("-", " ").replace("_", " ").replace("%20", " ").split())


def is_remote_posting(item: dict, loc: str) -> bool:
    # isRemote is often true for on-site roles (it means "remote allowed somewhere"); workplaceType is reliable
    wt = (item.get("workplaceType") or "").lower()
    if wt:
        return wt == "remote"
    return is_remote(loc)


def fetch(cfg: dict, search: dict, http: httpx.Client) -> list[Job]:
    jobs: list[Job] = []
    for company in cfg.get("companies", []):
        r = http.get(f"https://api.ashbyhq.com/posting-api/job-board/{company}")
        if r.status_code == 404:
            continue
        r.raise_for_status()
        for item in r.json().get("jobs", []):
            if item.get("isListed") is False:
                continue
            title = (item.get("title") or "").strip()
            loc = item.get("location", "")
            secondary = [s.get("location", "") for s in item.get("secondaryLocations") or []]
            if secondary:
                loc = "; ".join([loc, *secondary])
            jobs.append(Job(
                source="ashby",
                external_id=f"{company}:{item['id']}",
                company=company_name(company),
                title=title,
                url=item.get("jobUrl", ""),
                apply_url=item.get("applyUrl") or item.get("jobUrl", ""),
                location=loc,
                description=item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml")),
                job_type=guess_job_type(title, item.get("employmentType", "")),
                remote=is_remote_posting(item, loc),
                posted_at=item.get("publishedAt", ""),
                extra={"department": item.get("department"), "team": item.get("team"), "board": company,
                       "workplace": item.get("workplaceType")},
            ))
    return jobs
