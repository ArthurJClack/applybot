"""Job discovery sources. Each source exposes `fetch(cfg: dict, search: dict, http: httpx.Client) -> list[Job]`."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Callable

import httpx
from bs4 import BeautifulSoup

from applybot.models import Job

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ApplyBot/0.1 (+personal job search tool)"


def make_client() -> httpx.Client:
    return httpx.Client(timeout=45, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    raw = html.unescape(raw)  # some APIs double-escape HTML
    text = BeautifulSoup(raw, "html.parser").get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def iso_from_epoch(value) -> str:
    if value in (None, ""):
        return ""
    v = float(value)
    if v > 1e12:  # milliseconds
        v /= 1000
    return datetime.fromtimestamp(v, tz=timezone.utc).isoformat(timespec="seconds")


def guess_job_type(*texts: str) -> str:
    t = " ".join(x or "" for x in texts).lower()
    if any(w in t for w in ("intern", "co-op", "coop", "apprentice")):
        return "internship"
    if "part-time" in t or "part time" in t:
        return "part-time"
    if "contract" in t or "freelance" in t:
        return "contract"
    return "full-time"


def is_remote(*texts: str) -> bool:
    t = " ".join(x or "" for x in texts).lower()
    return "remote" in t or "anywhere" in t


def registry() -> dict[str, Callable]:
    from applybot.sources import ashby, boards, greenhouse, jobspy_source, lever, simplify
    return {
        "simplify": simplify.fetch,
        "greenhouse": greenhouse.fetch,
        "lever": lever.fetch,
        "ashby": ashby.fetch,
        "remotive": boards.fetch_remotive,
        "remoteok": boards.fetch_remoteok,
        "arbeitnow": boards.fetch_arbeitnow,
        "jobspy": jobspy_source.fetch,
    }


__all__ = ["Job", "make_client", "html_to_text", "iso_from_epoch", "guess_job_type", "is_remote", "registry"]
