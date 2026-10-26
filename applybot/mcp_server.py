"""ApplyBot as an MCP server, so Claude (Claude Desktop / Claude Code) can drive it from chat.

Claude does the thinking (scoring, choosing resume content) with your Claude subscription - no API key needed.
ApplyBot does the doing (job search, truthful resume rendering, form filling) and keeps its guard rails:
tailored resumes can only reuse facts from profile.txt, whatever Claude sends.

Run:  python -m applybot.mcp_server        (stdio)     env: APPLYBOT_CONFIG=<path to config.yaml>
"""
from __future__ import annotations

import contextlib
import functools
import json
import logging
import os
import sys
from pathlib import Path

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from applybot.config import load_config
from applybot.db import DB, STATUSES, SUBMITTED
from applybot.llm import LLM
from applybot.profile import profile_to_text

mcp = FastMCP("applybot")
_BLURB = 600
logging.getLogger("fontTools").setLevel(logging.WARNING)


def _tool(fn):
    """Register a tool. stdout is the MCP channel, so anything a library prints goes to stderr instead."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with contextlib.redirect_stdout(sys.stderr):
            return fn(*args, **kwargs)
    return mcp.tool()(wrapper)


def _config_path() -> Path:
    if os.environ.get("APPLYBOT_CONFIG"):
        return Path(os.environ["APPLYBOT_CONFIG"])
    from applybot.ui.launcher import default_data_dir
    return default_data_dir() / "config.yaml"


def _ctx():
    cfg = load_config(_config_path())
    return cfg, LLM(cfg["ai"]), DB(cfg.path("database"))


def _profile(cfg, llm):
    from applybot.profile import load_profile
    return load_profile(cfg.path("profile", "path"), llm, cfg["profile"].get("parser", "auto"),
                        cfg.path("profile", "cache_path"))


def _brief(j: dict, with_text: bool = False) -> dict:
    d = {k: j.get(k) for k in ("id", "company", "title", "location", "remote", "job_type", "status", "score",
                               "score_reason", "posted_at", "url")}
    if with_text:
        d["description_excerpt"] = (j.get("description") or "")[:_BLURB]
    return d


@_tool
def status() -> dict:
    """Pipeline overview: job counts by status, applications sent today, and whether built-in AI is configured."""
    cfg, llm, db = _ctx()
    try:
        return {"jobs_by_status": db.status_counts(), "applied_today": db.applied_today(),
                "daily_cap": cfg["apply"].get("max_per_day"), "built_in_ai": llm.available,
                "data_dir": str(cfg.base_dir)}
    finally:
        db.close()


@_tool
def get_profile() -> str:
    """The candidate's profile (education, experience, projects, skills, preferences). Read before scoring/tailoring.
    Everything in a tailored resume must come from this."""
    cfg, llm, db = _ctx()
    try:
        return profile_to_text(_profile(cfg, llm))
    finally:
        db.close()


@_tool
def search_jobs() -> dict:
    """Fetch new postings from all enabled sources (Simplify, Greenhouse, Lever, Ashby, ...), apply the filters in
    config.yaml and store new ones. Takes a minute or two."""
    from applybot.matcher import discover
    cfg, _, db = _ctx()
    try:
        return discover(cfg, db, log=lambda *_: None)
    finally:
        db.close()


@_tool
def list_jobs(status: str = "new", limit: int = 15, unscored_only: bool = False, with_excerpt: bool = False) -> list[dict]:
    """List tracked jobs. status: one of new, matched, rejected, tailored, applied, interviewing, offer,
    rejected_by_company, needs_review, failed, skipped ('' = any). Use with_excerpt=True to see the start of each
    description when scoring."""
    cfg, _, db = _ctx()
    try:
        return [_brief(j, with_excerpt) for j in db.list_jobs(status=status or None, limit=min(limit, 50),
                                                              unscored=unscored_only, order="date" if unscored_only else "score")]
    finally:
        db.close()


@_tool
def get_job(job_id: str) -> dict:
    """Full details for one job including the whole description (fetched from the ATS if missing)."""
    from applybot.pipeline import ensure_description
    cfg, _, db = _ctx()
    try:
        job = db.get_job(job_id)
        if not job:
            return {"error": f"job {job_id} not found (or id prefix is ambiguous)"}
        job = ensure_description(db, job)
        return {**_brief(job), "apply_url": job.get("apply_url"), "description": job.get("description", "")}
    finally:
        db.close()


@_tool
def set_score(job_id: str, score: float, reason: str) -> dict:
    """Record your 0-100 fit score for a job. Scores >= matching.min_score in config become 'matched', others
    'rejected'. Base it on get_profile + get_job; mention missing requirements in the reason."""
    cfg, _, db = _ctx()
    try:
        job = db.get_job(job_id)
        if not job:
            return {"error": f"job {job_id} not found"}
        score = max(0.0, min(100.0, float(score)))
        new = "matched" if score >= float(cfg["matching"].get("min_score", 60)) else "rejected"
        db.update_job(job["id"], score=score, score_reason=reason[:500], status=new)
        return {"id": job["id"], "score": score, "status": new}
    finally:
        db.close()


@_tool
def tailor_resume(job_id: str, plan: dict) -> dict:
    """Create the tailored resume + cover letter for a job from YOUR plan. plan = {"summary": str,
    "experience": [{"ref": int, "bullets": [str]}], "projects": [...], "leadership": [...],
    "skills": [{"category": str, "items": [str]}], "cover_letter": str (optional plain text)}.
    'ref' is the zero-based index into get_profile's arrays. Rephrase to match the posting's wording ONLY where it is
    true; the tool drops invented numbers/skills and copies employers, titles and dates from the profile.
    Returns file paths and an ATS keyword report (covered / available-but-omitted / real gaps)."""
    from applybot.pipeline import ensure_description, job_dir, slug
    from applybot.profile import split_name
    from applybot.render import render_docx, render_letter_pdf, render_markdown, render_pdf
    from applybot.tailor import apply_ai_plan, boost_skills, format_report, keyword_report
    cfg, llm, db = _ctx()
    try:
        job = db.get_job(job_id)
        if not job:
            return {"error": f"job {job_id} not found"}
        job = ensure_description(db, job)
        profile = _profile(cfg, llm)
        resume = boost_skills(apply_ai_plan(profile, plan or {}), profile, job)
        out = job_dir(cfg, job)
        first, last = split_name(profile)
        who = slug(f"{first}_{last}", 40) if first else "Candidate"
        formats = cfg["apply"].get("resume_formats") or ["pdf"]
        files = []
        if "pdf" in formats:
            files.append(str(render_pdf(resume, out / f"{who}_Resume.pdf")))
        if "docx" in formats:
            files.append(str(render_docx(resume, out / f"{who}_Resume.docx")))
        (out / "resume.md").write_text(render_markdown(resume), encoding="utf-8")
        (out / "resume.json").write_text(json.dumps(resume, indent=2), encoding="utf-8")
        (out / "job.json").write_text(json.dumps(job, indent=2, default=str), encoding="utf-8")
        letter = (plan or {}).get("cover_letter")
        if isinstance(letter, str) and letter.strip():
            (out / "cover_letter.txt").write_text(letter.strip(), encoding="utf-8")
            files.append(str(render_letter_pdf(letter.strip(), profile.get("contact", {}),
                                               out / f"{who}_Cover_Letter.pdf")))
        report = keyword_report(resume, profile, job)
        (out / "ats_report.txt").write_text(format_report(report), encoding="utf-8")
        if job["status"] in ("new", "matched"):
            db.update_job(job["id"], status="tailored")
        return {"folder": str(out), "files": files, "ats": report}
    finally:
        db.close()


@_tool
def mark_job(job_id: str, status: str) -> dict:
    """Manually set a job's status (e.g. interviewing, offer, rejected_by_company, skipped, applied)."""
    cfg, _, db = _ctx()
    try:
        if status not in STATUSES:
            return {"error": f"status must be one of {', '.join(STATUSES)}"}
        job = db.get_job(job_id)
        if not job:
            return {"error": f"job {job_id} not found"}
        db.update_job(job["id"], status=status)
        return {"id": job["id"], "status": status}
    finally:
        db.close()


@_tool
def apply_to_jobs(job_ids: list[str], mode: str = "dry_run", confirm_submit: bool = False) -> list[dict]:
    """Open each application form in a real browser window and fill it (resume, cover letter, saved answers).
    mode 'dry_run' (default) fills but never submits and saves a screenshot. mode 'auto' SUBMITS - it only runs
    if confirm_submit=True, so ask the user first. CAPTCHAs, logins and unknown required questions stop that job
    as 'needs_review'. Daily/per-company caps from config.yaml apply. Slow: ~1 minute per job."""
    from applybot.pipeline import apply_jobs
    if mode not in ("dry_run", "auto"):
        return [{"error": "mode must be 'dry_run' or 'auto' here (use the ApplyBot app for interactive review)"}]
    if mode == "auto" and not confirm_submit:
        return [{"error": "auto mode submits real applications - ask the user, then call again with confirm_submit=true"}]
    cfg, llm, db = _ctx()
    try:
        jobs = [j for j in (db.get_job(i) for i in job_ids) if j]
        if not jobs:
            return [{"error": "no matching jobs"}]
        profile = _profile(cfg, llm)
        res = apply_jobs(cfg, db, profile, llm, jobs, mode, log=lambda *_: None)
        return [{"id": r["job"]["id"], "company": r["job"]["company"], "title": r["job"]["title"],
                 "status": r["result"].status, "notes": r["result"].notes, "screenshot": r["result"].screenshot}
                for r in res] or [{"note": "nothing was applied to (already submitted, or a cap was reached)"}]
    finally:
        db.close()


def main():
    mcp.run()


if __name__ == "__main__":
    main()
