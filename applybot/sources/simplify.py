"""SimplifyJobs GitHub listings (internships + new grad). Huge, curated, frequently updated."""
from __future__ import annotations

import httpx

from applybot.models import Job
from applybot.sources import iso_from_epoch, is_remote


def fetch(cfg: dict, search: dict, http: httpx.Client) -> list[Job]:
    jobs: list[Job] = []
    for repo in cfg.get("repos", []):
        url = f"https://raw.githubusercontent.com/{repo}/dev/.github/scripts/listings.json"
        r = http.get(url)
        r.raise_for_status()
        default_type = "internship" if "intern" in repo.lower() else "full-time"
        for item in r.json():
            if not item.get("active", True) or not item.get("is_visible", True) or not item.get("url"):
                continue
            locations = item.get("locations") or []
            loc = "; ".join(locations)
            jobs.append(Job(
                source="simplify",
                external_id=str(item.get("id")),
                company=item.get("company_name", ""),
                title=item.get("title", ""),
                url=item["url"],
                apply_url=item["url"],
                location=loc,
                job_type=default_type,
                remote=is_remote(loc),
                posted_at=iso_from_epoch(item.get("date_posted") or item.get("date_updated")),
                extra={k: item.get(k) for k in ("category", "terms", "sponsorship", "degrees") if item.get(k)},
            ))
    return jobs
