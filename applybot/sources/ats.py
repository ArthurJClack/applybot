"""Recognize postings hosted on Greenhouse / Lever / Ashby and pull their full description from the public API.

Aggregators like SimplifyJobs only give a link; this turns that link into a real description so scoring and
tailoring have something to work with.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

from applybot.sources import html_to_text, make_client

_GH = re.compile(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", re.I)
_LEVER = re.compile(r"jobs\.(eu\.)?lever\.co/([\w.-]+)/([0-9a-f-]{36})", re.I)
_ASHBY = re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)/([0-9a-f-]{36})", re.I)

_ashby_cache: dict[str, dict[str, dict]] = {}


def ats_key(*urls: str | None) -> tuple[str, str, str, str] | None:
    """(ats, board, job_id, region) for the first URL that points at a known ATS, else None."""
    for url in urls:
        if not url:
            continue
        m = _GH.search(url)
        if m:
            return ("greenhouse", m.group(1).lower(), m.group(2), "")
        m = _LEVER.search(url)
        if m:
            return ("lever", m.group(2).lower(), m.group(3).lower(), "eu" if m.group(1) else "")
        m = _ASHBY.search(url)
        if m:
            return ("ashby", m.group(1).lower(), m.group(2).lower(), "")
        # e.g. stripe.com/jobs/search?gh_jid=123 - id is known but board token isn't
        q = parse_qs(urlparse(url).query)
        if q.get("gh_jid"):
            host = (urlparse(url).hostname or "").split(".")
            board = host[-2] if len(host) >= 2 else ""
            if board:
                return ("greenhouse", board.lower(), q["gh_jid"][0], "")
    return None


def dedupe_key(*urls: str | None) -> str:
    k = ats_key(*urls)
    return f"{k[0]}:{k[1]}:{k[2]}" if k else ""


def _greenhouse(board: str, jid: str, http: httpx.Client) -> str:
    r = http.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}")
    if r.status_code != 200:
        return ""
    return html_to_text(r.json().get("content"))


def _lever(slug: str, pid: str, region: str, http: httpx.Client) -> str:
    host = "api.eu.lever.co" if region == "eu" else "api.lever.co"
    r = http.get(f"https://{host}/v0/postings/{slug}/{pid}", params={"mode": "json"})
    if r.status_code != 200:
        return ""
    item = r.json()
    parts = [item.get("descriptionPlain", ""),
             *[f"{lst.get('text', '')}\n{lst.get('content', '')}" for lst in item.get("lists", [])],
             item.get("additionalPlain", "")]
    return html_to_text("\n\n".join(p for p in parts if p))


def _ashby(slug: str, jid: str, http: httpx.Client) -> str:
    if slug not in _ashby_cache:
        r = http.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        _ashby_cache[slug] = {j.get("id", "").lower(): j for j in r.json().get("jobs", [])} if r.status_code == 200 else {}
    item = _ashby_cache[slug].get(jid)
    if not item:
        return ""
    return item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml"))


def ats_description(*urls: str | None, http: httpx.Client | None = None) -> str:
    """Full posting text via the ATS's public API, or '' if the URL isn't a known ATS or the call fails."""
    key = ats_key(*urls)
    if not key:
        return ""
    ats, board, jid, region = key
    own = http is None
    http = http or make_client()
    try:
        if ats == "greenhouse":
            return _greenhouse(board, jid, http)
        if ats == "lever":
            return _lever(board, jid, region, http)
        return _ashby(board, jid, http)
    except (httpx.HTTPError, ValueError):
        return ""
    finally:
        if own:
            http.close()
