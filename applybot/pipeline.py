"""High-level operations shared by the CLI: document generation and applying to jobs."""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from applybot.answers import AnswerBank, terminal_prompt
from applybot.config import Config
from applybot.db import DB, SUBMITTED
from applybot.llm import LLM
from applybot.models import Job
from applybot.profile import split_name
from applybot.render import render_docx, render_letter_pdf, render_markdown, render_pdf
from applybot.tailor import cover_letter, fetch_description, format_report, keyword_report, tailor_resume


def slug(text: str, n: int = 40) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")[:n] or "job"


def job_dir(cfg: Config, job: dict, create: bool = True) -> Path:
    d = cfg.path("apply", "output_dir") / f"{slug(job.get('company'), 25)}_{slug(job.get('title'), 40)}_{job['id']}"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_description(db: DB | None, job: dict) -> dict:
    if not (job.get("description") or "").strip():
        desc = fetch_description(job.get("url") or job.get("apply_url"), 30, job.get("apply_url") or "")
        if desc:
            job["description"] = desc
            if db is not None:
                db.update_job(job["id"], description=desc)
    return job


def prepare_documents(cfg: Config, profile: dict, llm: LLM, job: dict, db: DB | None = None,
                      log: Callable[[str], None] = print) -> dict:
    job = ensure_description(db, job)
    out = job_dir(cfg, job)
    resume, method = tailor_resume(profile, job, llm)
    formats = cfg["apply"].get("resume_formats") or ["pdf"]
    first, last = split_name(profile)
    who = slug(f"{first}_{last}", 40) if first else "Candidate"
    base = f"{who}_Resume"
    paths: dict[str, Path] = {}
    if "pdf" in formats:
        paths["resume"] = render_pdf(resume, out / f"{base}.pdf")
    if "docx" in formats:
        paths["resume_docx"] = render_docx(resume, out / f"{base}.docx")
        paths.setdefault("resume", paths["resume_docx"])
    md = render_markdown(resume)
    (out / "resume.md").write_text(md, encoding="utf-8")
    (out / "resume.json").write_text(json.dumps(resume, indent=2), encoding="utf-8")
    (out / "job.json").write_text(json.dumps(job, indent=2, default=str), encoding="utf-8")
    report = keyword_report(resume, profile, job)
    (out / "ats_report.txt").write_text(format_report(report), encoding="utf-8")
    if report["considered"]:
        log(f"  ATS keyword coverage: {report['coverage']}% of the posting's top terms")

    letter = ""
    if cfg["apply"].get("cover_letter", True):
        letter = cover_letter(profile, job, llm)
        (out / "cover_letter.txt").write_text(letter, encoding="utf-8")
        paths["cover_letter"] = render_letter_pdf(letter, profile.get("contact", {}),
                                                  out / f"{who}_Cover_Letter.pdf")
    log(f"  documents ({method}) -> {out}")
    return {"dir": out, "paths": paths, "resume": resume, "resume_md": md, "cover_letter": letter, "method": method}


def manual_job(url: str, company: str = "", title: str = "", description: str = "") -> Job:
    host = urlparse(url).netloc.replace("www.", "")
    return Job(source="manual", external_id=url, company=company or host.split(".")[0].title(),
               title=title or "Application", url=url, apply_url=url, description=description)


def over_company_cap(counts: dict[str, int], company_key: str, max_company: int) -> bool:
    return bool(max_company) and bool(company_key) and counts.get(company_key, 0) >= max_company


def apply_jobs(cfg: Config, db: DB, profile: dict, llm: LLM, jobs: list[dict], mode: str,
               log: Callable[[str], None] = print, ask_human: Callable | None = None,
               pause: Callable | None = None) -> list[dict]:
    from applybot.apply.browser import Applicant

    if mode == "review":
        cfg["apply"]["headless"] = False  # the human has to see the form to approve it
    max_day = int(cfg["apply"].get("max_per_day", 25) or 0)  # 0 = no daily limit
    max_company = int(cfg["apply"].get("max_per_company", 0) or 0)  # 0 = no per-company cap
    company_counts = db.company_app_counts() if max_company else {}
    delay = cfg["apply"].get("delay_seconds") or [0, 0]
    interactive_human = (ask_human or terminal_prompt) if mode == "review" else None
    results = []
    with Applicant(cfg, profile, AnswerBank(cfg.path("profile", "answers_path"), profile), llm, log=log,
                   ask_human=interactive_human, pause=pause) as applicant:
        for i, job in enumerate(jobs):
            if mode != "dry_run" and max_day and db.applied_today() >= max_day:
                log(f"[yellow]Daily cap of {max_day} applications reached - stopping.[/yellow]")
                break
            company_key = (job.get("company") or "").lower()
            if mode != "dry_run" and job.get("status") in SUBMITTED:
                log(f"[yellow]Skipping {job['company']} - {job['title']}: already marked "
                    f"'{job['status']}' - not applying twice.[/yellow]")
                continue
            if mode != "dry_run" and over_company_cap(company_counts, company_key, max_company):
                log(f"[yellow]Skipping {job['company']} - {job['title']}: already sent "
                    f"{company_counts[company_key]} application(s) to {job['company']} (apply.max_per_company = "
                    f"{max_company}).[/yellow]")
                continue
            log(f"\n[bold cyan]({i + 1}/{len(jobs)}) {job['company']} - {job['title']}[/bold cyan]  (id {job['id']})")
            log(f"  {job.get('apply_url') or job.get('url')}")
            docs = prepare_documents(cfg, profile, llm, job, db, log)
            applicant.bank.cover_letter_text = docs["cover_letter"]
            applicant.bank.resume_text = docs["resume_md"]
            files = {k: v for k, v in (("resume", docs["paths"].get("resume")),
                                       ("cover_letter", docs["paths"].get("cover_letter"))) if v}
            transcript = (applicant.bank.data.get("files") or {}).get("transcript")
            if transcript and Path(transcript).exists():
                files["transcript"] = Path(transcript)
            res = applicant.apply(job.get("apply_url") or job["url"], job, files, mode, docs["dir"])
            color = {"applied": "green", "dry_run": "blue", "skipped": "white"}.get(res.status, "yellow")
            log(f"  -> [{color}]{res.status}[/{color}]: {res.notes}")
            new_status = {"applied": "applied", "needs_review": "needs_review", "failed": "failed",
                          "skipped": "skipped", "dry_run": "tailored"}[res.status]
            db.update_job(job["id"], status=new_status)
            db.log_application(job["id"], res.final_url or job.get("apply_url", ""), res.status, mode,
                               str(docs["paths"].get("resume", "")), str(docs["paths"].get("cover_letter", "")),
                               res.answers, res.notes)
            results.append({"job": job, "result": res})
            if res.status == "applied":
                company_counts[company_key] = company_counts.get(company_key, 0) + 1
            if i < len(jobs) - 1 and res.status == "applied" and delay and max(delay) > 0:
                wait = random.uniform(float(delay[0]), float(delay[-1]))
                log(f"  waiting {wait:.0f}s before the next application...")
                time.sleep(wait)
    return results
