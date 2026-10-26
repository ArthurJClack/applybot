"""General public job-board APIs: Remotive, RemoteOK, Arbeitnow."""
from __future__ import annotations

import httpx

from applybot.models import Job
from applybot.sources import guess_job_type, html_to_text, iso_from_epoch, is_remote


def fetch_remotive(cfg: dict, search: dict, http: httpx.Client) -> list[Job]:
    jobs: dict[str, Job] = {}
    for kw in search.get("keywords") or [""]:
        r = http.get("https://remotive.com/api/remote-jobs", params={"search": kw, "limit": 200})
        r.raise_for_status()
        for item in r.json().get("jobs", []):
            title = item.get("title", "")
            jobs[str(item["id"])] = Job(
                source="remotive",
                external_id=str(item["id"]),
                company=item.get("company_name", ""),
                title=title,
                url=item.get("url", ""),
                apply_url=item.get("url", ""),
                location=item.get("candidate_required_location", "") or "Remote",
                description=html_to_text(item.get("description")),
                job_type=guess_job_type(title, item.get("job_type", "")),
                remote=True,
                posted_at=item.get("publication_date", ""),
                extra={"category": item.get("category"), "salary": item.get("salary")},
            )
    return list(jobs.values())


def fetch_remoteok(cfg: dict, search: dict, http: httpx.Client) -> list[Job]:
    r = http.get("https://remoteok.com/api")
    r.raise_for_status()
    jobs = []
    for item in r.json():
        if "id" not in item or "position" not in item:
            continue  # first element is a legal notice
        title = item.get("position", "")
        jobs.append(Job(
            source="remoteok",
            external_id=str(item["id"]),
            company=item.get("company", ""),
            title=title,
            url=item.get("url", ""),
            apply_url=item.get("apply_url") or item.get("url", ""),
            location=item.get("location") or "Remote",
            description=html_to_text(item.get("description")),
            job_type=guess_job_type(title, " ".join(item.get("tags") or [])),
            remote=True,
            posted_at=item.get("date", ""),
            extra={"tags": item.get("tags")},
        ))
    return jobs


def fetch_arbeitnow(cfg: dict, search: dict, http: httpx.Client) -> list[Job]:
    jobs = []
    for page in range(1, int(cfg.get("pages", 3)) + 1):
        r = http.get("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            break
        for item in data:
            title = item.get("title", "")
            loc = item.get("location", "")
            jobs.append(Job(
                source="arbeitnow",
                external_id=item.get("slug", ""),
                company=item.get("company_name", ""),
                title=title,
                url=item.get("url", ""),
                apply_url=item.get("url", ""),
                location=loc,
                description=html_to_text(item.get("description")),
                job_type=guess_job_type(title, " ".join(item.get("job_types") or [])),
                remote=bool(item.get("remote")) or is_remote(loc),
                posted_at=iso_from_epoch(item.get("created_at")),
                extra={"tags": item.get("tags")},
            ))
    return jobs
