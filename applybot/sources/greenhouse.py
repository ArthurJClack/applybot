"""Greenhouse public job board API (no auth). `companies` are board tokens, e.g. boards.greenhouse.io/<token>."""
from __future__ import annotations

import httpx

from applybot.models import Job
from applybot.sources import guess_job_type, html_to_text, is_remote


def fetch(cfg: dict, search: dict, http: httpx.Client) -> list[Job]:
    jobs: list[Job] = []
    for company in cfg.get("companies", []):
        r = http.get(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs", params={"content": "true"})
        if r.status_code == 404:
            continue
        r.raise_for_status()
        for item in r.json().get("jobs", []):
            loc = (item.get("location") or {}).get("name", "")
            desc = html_to_text(item.get("content"))
            title = item.get("title", "")
            jobs.append(Job(
                source="greenhouse",
                external_id=f"{company}:{item['id']}",
                company=item.get("company_name") or company,
                title=title,
                url=item.get("absolute_url", ""),
                apply_url=f"https://job-boards.greenhouse.io/{company}/jobs/{item['id']}",
                location=loc,
                description=desc,
                job_type=guess_job_type(title),
                remote=is_remote(loc, title),
                posted_at=item.get("first_published") or item.get("updated_at") or "",
                extra={"board": company},
            ))
    return jobs
