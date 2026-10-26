"""Lever public postings API (no auth). `companies` are slugs from jobs.lever.co/<slug>."""
from __future__ import annotations

import httpx

from applybot.models import Job
from applybot.sources.ashby import company_name
from applybot.sources import guess_job_type, html_to_text, iso_from_epoch, is_remote


def fetch(cfg: dict, search: dict, http: httpx.Client) -> list[Job]:
    jobs: list[Job] = []
    for company in cfg.get("companies", []):
        r = http.get(f"https://api.lever.co/v0/postings/{company}", params={"mode": "json"})
        if r.status_code == 404:
            continue
        r.raise_for_status()
        for item in r.json():
            cats = item.get("categories") or {}
            loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
            title = item.get("text", "")
            desc = "\n\n".join(filter(None, [
                item.get("descriptionPlain", ""),
                *[f"{lst.get('text', '')}\n{lst.get('content', '')}" for lst in item.get("lists", [])],
                item.get("additionalPlain", ""),
            ]))
            jobs.append(Job(
                source="lever",
                external_id=f"{company}:{item['id']}",
                company=company_name(company),
                title=title,
                url=item.get("hostedUrl", ""),
                apply_url=item.get("applyUrl") or item.get("hostedUrl", ""),
                location=loc,
                description=html_to_text(desc),
                job_type=guess_job_type(title, cats.get("commitment", "")),
                remote=is_remote(loc, item.get("workplaceType", "")),
                posted_at=iso_from_epoch(item.get("createdAt")),
                extra={"team": cats.get("team"), "commitment": cats.get("commitment")},
            ))
    return jobs
