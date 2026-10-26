"""Optional LinkedIn/Indeed/Glassdoor/ZipRecruiter search via the `python-jobspy` package.

Install with `pip install python-jobspy`. Those sites restrict automated access; use responsibly and at low volume.
"""
from __future__ import annotations

import httpx

from applybot.models import Job
from applybot.sources import guess_job_type, is_remote


def fetch(cfg: dict, search: dict, http: httpx.Client) -> list[Job]:
    try:
        from jobspy import scrape_jobs  # type: ignore
    except ImportError as e:
        raise RuntimeError("jobspy source enabled but `python-jobspy` is not installed "
                           "(pip install python-jobspy)") from e

    jobs: list[Job] = []
    for kw in search.get("keywords") or []:
        df = scrape_jobs(
            site_name=cfg.get("sites", ["indeed"]),
            search_term=kw,
            location=cfg.get("location") or None,
            results_wanted=int(cfg.get("results_wanted", 50)),
            hours_old=cfg.get("hours_old"),
            country_indeed=cfg.get("country_indeed", "USA"),
        )
        for row in df.to_dict("records"):
            def g(k):
                v = row.get(k)
                return "" if v is None or (isinstance(v, float) and v != v) else str(v)
            title = g("title")
            loc = g("location")
            jobs.append(Job(
                source=f"jobspy:{g('site')}",
                external_id=g("id") or g("job_url"),
                company=g("company"),
                title=title,
                url=g("job_url"),
                apply_url=g("job_url_direct") or g("job_url"),
                location=loc,
                description=g("description"),
                job_type=guess_job_type(title, g("job_type")),
                remote=g("is_remote").lower() == "true" or is_remote(loc),
                posted_at=g("date_posted"),
            ))
    return jobs
