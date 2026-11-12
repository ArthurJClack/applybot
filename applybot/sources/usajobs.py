"""USAJOBS (federal jobs) through the official search API at data.usajobs.gov.

Needs a free API key: request one at https://developer.usajobs.gov/apirequest/ (it is emailed to you), then set
in config.yaml (or .env):

    search:
      sources:
        usajobs:
          enabled: true
          api_key: ${USAJOBS_API_KEY}
          email: ${USAJOBS_EMAIL}     # the address you requested the key with; USAJOBS requires it as User-Agent
          keywords: ["information technology", "software", "IT specialist"]   # optional, else search.keywords
          location: ""                # optional, e.g. "Washington" or "Tacoma, Washington"; empty = nationwide
          students_only: false        # true = only Pathways / student hiring paths
          remote_only: false

Applying on USAJOBS needs a login.gov sign-in and agency questionnaires, so these jobs go through assist mode
(you sign in and answer the self-assessment), never auto.
"""
from __future__ import annotations

import httpx

from applybot.models import Job
from applybot.sources import guess_job_type, html_to_text, is_remote

API = "https://data.usajobs.gov/api/search"
PAGE_SIZE = 500


def _job(d: dict) -> Job:
    title = d.get("PositionTitle", "")
    locs = d.get("PositionLocation") or []
    loc = d.get("PositionLocationDisplay") or "; ".join(x.get("LocationName", "") for x in locs)
    details = (d.get("UserArea") or {}).get("Details") or {}
    schedule = ", ".join(s.get("Name", "") for s in d.get("PositionSchedule") or [])
    pay = (d.get("PositionRemuneration") or [{}])[0]
    desc = "\n\n".join(filter(None, [
        details.get("JobSummary", ""),
        d.get("QualificationSummary", ""),
        "Major duties:\n" + "\n".join(details.get("MajorDuties") or []) if details.get("MajorDuties") else "",
    ]))
    apply = (d.get("ApplyURI") or [d.get("PositionURI", "")])[0]
    remote = bool(details.get("RemoteIndicator")) or is_remote(loc)
    student = any("student" in str(h).lower() for h in details.get("HiringPath") or [])
    return Job(
        source="usajobs",
        external_id=str(d.get("PositionID") or d.get("PositionURI", "")),
        company=d.get("OrganizationName") or d.get("DepartmentName") or "U.S. Government",
        title=title,
        url=d.get("PositionURI", ""),
        apply_url=apply,
        location=loc,
        description=html_to_text(desc),
        job_type="internship" if student and "intern" in title.lower() else guess_job_type(title, schedule),
        remote=remote,
        posted_at=d.get("PublicationStartDate", ""),
        extra={"department": d.get("DepartmentName"), "grade": (d.get("JobGrade") or [{}])[0].get("Code"),
               "pay": f"{pay.get('MinimumRange', '')}-{pay.get('MaximumRange', '')} {pay.get('Description', '')}".strip(" -"),
               "closes": d.get("ApplicationCloseDate"), "hiring_path": details.get("HiringPath"),
               "requires_login": True},
    )


def fetch(cfg: dict, search: dict, http: httpx.Client) -> list[Job]:
    key, email = (cfg.get("api_key") or "").strip(), (cfg.get("email") or "").strip()
    if not key or not email:
        raise ValueError("usajobs needs api_key and email (free key: https://developer.usajobs.gov/apirequest/)")
    headers = {"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key}
    keywords = cfg.get("keywords") or search.get("keywords") or [""]
    jobs: dict[str, Job] = {}
    for kw in keywords:
        params = {"Keyword": kw, "ResultsPerPage": PAGE_SIZE, "WhoMayApply": "public", "Fields": "full"}
        if cfg.get("location"):
            params["LocationName"] = cfg["location"]
        if cfg.get("students_only"):
            params["HiringPath"] = "student"
        if cfg.get("remote_only"):
            params["RemoteIndicator"] = "True"
        for page in range(1, int(cfg.get("max_pages", 2)) + 1):
            r = http.get(API, params={**params, "Page": page}, headers=headers)
            r.raise_for_status()
            result = (r.json() or {}).get("SearchResult") or {}
            items = result.get("SearchResultItems") or []
            for it in items:
                job = _job(it.get("MatchedObjectDescriptor") or {})
                if job.external_id:
                    jobs[job.external_id] = job
            if len(items) < PAGE_SIZE:
                break
    return list(jobs.values())
