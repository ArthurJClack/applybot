"""Command line interface: `python -m applybot <command>` (or `python main.py <command>`)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from applybot.config import load_config
from applybot.db import DB, STATUSES
from applybot.llm import LLM, LLMError

console = Console()
log = console.print
TEMPLATES = Path(__file__).parent / "templates"


def _ctx(args):
    cfg = load_config(args.config)
    llm = LLM(cfg["ai"])
    db = DB(cfg.path("database"))
    return cfg, llm, db


def _profile(cfg, llm, refresh=False):
    from applybot.profile import load_profile
    return load_profile(cfg.path("profile", "path"), llm, cfg["profile"].get("parser", "auto"),
                        cfg.path("profile", "cache_path"), refresh=refresh)


def _job_table(jobs: list[dict], title: str = "Jobs") -> Table:
    t = Table(title=title, show_lines=False)
    for col in ("id", "score", "status", "company", "title", "location", "source", "posted"):
        t.add_column(col, overflow="fold", no_wrap=col in ("id", "score", "status", "posted"),
                     max_width=40 if col in ("title", "location") else None)
    for j in jobs:
        t.add_row(j["id"], "" if j.get("score") is None else f"{j['score']:.0f}", j.get("status", ""),
                  j.get("company", ""), j.get("title", ""), (j.get("location") or "")[:60], j.get("source", ""),
                  (j.get("posted_at") or "")[:10])
    return t


# ---------------------------------------------------------------------- commands
def cmd_init(args):
    from applybot.config import WORKSPACE_FILES, init_workspace
    base = Path(args.config).resolve().parent
    created = init_workspace(base)
    for _, dst in WORKSPACE_FILES:
        log(f"[green]created[/green]  {dst}" if dst in created else f"exists   {dst}")
    log("\nNext steps:\n  1. Put your API key in .env (or set ai.provider: none / ollama in config.yaml)\n"
        "  2. Fill in profile.txt with everything about you (any format works with AI)\n"
        "  3. Review answers.yaml (work authorization, EEO, etc.)\n"
        "  4. python main.py run --mode dry_run")


def cmd_profile(args):
    cfg, llm, _ = _ctx(args)
    p = _profile(cfg, llm, refresh=args.refresh)
    if args.json:
        console.print_json(json.dumps({k: v for k, v in p.items() if k != "raw"}))
        return
    c = p.get("contact", {})
    log(f"[bold]{c.get('name')}[/bold]  {c.get('email')}  {c.get('phone')}  {c.get('location')}")
    for section in ("education", "experience", "projects", "leadership"):
        log(f"[cyan]{section}[/cyan]: {len(p.get(section) or [])} entries")
    from applybot.profile import all_skills
    log(f"[cyan]skills[/cyan]: {', '.join(all_skills(p))}")
    log(f"[cyan]preferences[/cyan]: {p.get('preferences')}")


def cmd_search(args):
    from applybot.matcher import discover
    cfg, _, db = _ctx(args)
    stats = discover(cfg, db, log=log, only=args.source)
    log(f"\n[bold]{stats['new']} new jobs[/bold] stored ({stats['kept']} matched filters of {stats['fetched']} fetched)")


def cmd_score(args):
    from applybot.matcher import score_jobs
    cfg, llm, db = _ctx(args)
    if args.rescore:
        db.conn.execute("UPDATE jobs SET score=NULL, status='new' WHERE status IN ('matched','rejected')")
        db.conn.commit()
    profile = _profile(cfg, llm)
    n = score_jobs(db, profile, llm, cfg, limit=args.limit, log=log)
    log(f"\nscored {n} job(s)")


def cmd_list(args):
    _, _, db = _ctx(args)
    jobs = db.list_jobs(status=args.status, min_score=args.min_score, limit=args.limit)
    console.print(_job_table(jobs, f"Jobs ({args.status or 'all'})"))


def cmd_show(args):
    _, _, db = _ctx(args)
    job = db.get_job(args.job)
    if not job:
        log(f"[red]job {args.job} not found[/red]")
        return 1
    for k in ("id", "company", "title", "location", "job_type", "remote", "source", "posted_at", "url", "apply_url",
              "score", "score_reason", "status", "extra"):
        log(f"[cyan]{k:>12}[/cyan]: {job.get(k)}")
    log("\n" + (job.get("description") or "(no description)")[:3000])


def cmd_tailor(args):
    from applybot.pipeline import prepare_documents
    cfg, llm, db = _ctx(args)
    profile = _profile(cfg, llm)
    if args.no_cover:
        cfg["apply"]["cover_letter"] = False
    for jid in args.jobs:
        job = db.get_job(jid)
        if not job:
            log(f"[red]job {jid} not found[/red]")
            continue
        log(f"[bold]{job['company']} - {job['title']}[/bold]")
        docs = prepare_documents(cfg, profile, llm, job, db, log)
        for name, p in docs["paths"].items():
            log(f"  {name}: {p}")
        if job["status"] in ("new", "matched"):
            db.update_job(job["id"], status="tailored")


def cmd_apply(args):
    from applybot.pipeline import apply_jobs, manual_job
    cfg, llm, db = _ctx(args)
    mode = args.mode or cfg["apply"]["mode"]
    if args.headless:
        cfg["apply"]["headless"] = True
    profile = _profile(cfg, llm)
    jobs = []
    for url in args.url or []:
        mj = manual_job(url, args.company or "", args.title or "")
        db.upsert_job(mj)
        jobs.append(db.get_job(mj.id) or {**mj.to_dict(), "status": "new"})
    for jid in args.jobs:
        job = db.get_job(jid)
        if job:
            jobs.append(job)
        else:
            log(f"[red]job {jid} not found[/red]")
    if not jobs:
        log("nothing to apply to (pass job ids or --url)")
        return 1
    apply_jobs(cfg, db, profile, llm, jobs, mode, log)


def cmd_run(args):
    """Full pipeline: search -> score -> tailor -> apply."""
    from applybot.matcher import discover, score_jobs
    from applybot.pipeline import apply_jobs
    cfg, llm, db = _ctx(args)
    mode = args.mode or cfg["apply"]["mode"]
    if args.headless:
        cfg["apply"]["headless"] = True
    profile = _profile(cfg, llm)
    if not args.skip_search:
        log("[bold]1. Searching for postings[/bold]")
        discover(cfg, db, log=log)
    log("\n[bold]2. Scoring fit[/bold]")
    score_jobs(db, profile, llm, cfg, limit=args.score_limit, log=log)
    limit = args.max or int(cfg["apply"].get("max_per_run", 10))
    targets = db.list_jobs(status="matched", min_score=float(cfg["matching"].get("min_score", 60)), limit=limit)
    console.print(_job_table(targets, "3. Top matches to apply to"))
    if not targets:
        log("no matched jobs to apply to")
        return
    log(f"\n[bold]4. Applying (mode={mode})[/bold]")
    apply_jobs(cfg, db, profile, llm, targets, mode, log)
    cmd_status(args)


def cmd_refresh(args):
    """Search + score, no applying. Safe to run on a schedule: fresh scored matches every morning."""
    from applybot.matcher import discover, score_jobs
    cfg, llm, db = _ctx(args)
    profile = _profile(cfg, llm)
    log("[bold]1. Searching for postings[/bold]")
    discover(cfg, db, log=log)
    log("\n[bold]2. Scoring fit[/bold]")
    score_jobs(db, profile, llm, cfg, limit=args.score_limit, log=log)
    matches = db.list_jobs(status="matched", min_score=float(cfg["matching"].get("min_score", 60)), limit=args.top)
    if matches:
        console.print(_job_table(matches, f"Top {len(matches)} matches - review and apply when ready"))
    else:
        log("no new matches this time")


def cmd_export(args):
    cfg, _, db = _ctx(args)
    out = Path(args.out) if args.out else Path(args.config).resolve().parent / "export"
    for path in db.export_csv(out):
        log(f"[green]wrote[/green] {path}")


SCHEDULE_TASK_NAME = "ApplyBot daily refresh"


def _schedule_run_command(config_path: str) -> str:
    """The command the Windows scheduled task runs: refresh via this same install (exe or source)."""
    exe = Path(sys.executable).resolve()
    cfg = Path(config_path).resolve()
    if getattr(sys, "frozen", False):
        return f'"{exe}" --data "{cfg.parent}" refresh'
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    runner = f'"{exe}" "{main_py}"' if main_py.exists() else f'"{exe}" -m applybot'
    return f'{runner} -c "{cfg}" refresh'


def _schtasks_args(action: str, time: str = "", command: str = "") -> list[str]:
    if action == "create":
        return ["schtasks", "/Create", "/TN", SCHEDULE_TASK_NAME, "/TR", command, "/SC", "DAILY", "/ST", time, "/F"]
    if action == "delete":
        return ["schtasks", "/Delete", "/TN", SCHEDULE_TASK_NAME, "/F"]
    return ["schtasks", "/Query", "/TN", SCHEDULE_TASK_NAME]


def cmd_schedule(args):
    """Create/remove a Windows scheduled task that runs `refresh` daily (no auto-applying)."""
    import re as _re
    import subprocess
    if sys.platform != "win32":
        log("[red]schedule uses the Windows Task Scheduler and only works on Windows[/red]")
        return 1
    run = lambda a: subprocess.run(a, capture_output=True, text=True)
    if args.off:
        r = run(_schtasks_args("delete"))
        log("[green]daily refresh removed[/green]" if r.returncode == 0 else "no scheduled refresh was set up")
        return 0
    if not args.time:
        r = run(_schtasks_args("query"))
        log(r.stdout.strip() if r.returncode == 0
            else "No daily refresh scheduled. Set one up with: applybot schedule 08:45")
        return 0
    if not _re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", args.time):
        log(f"[red]{args.time!r} is not a valid time - use 24h HH:MM, e.g. 08:45[/red]")
        return 1
    cmd = _schedule_run_command(args.config)
    r = run(_schtasks_args("create", args.time, cmd))
    if r.returncode != 0:
        log(f"[red]could not create the scheduled task:[/red] {r.stderr.strip() or r.stdout.strip()}")
        return 1
    log(f"[green]done[/green] - every day at {args.time} ApplyBot will search and score new jobs.\n"
        f"It never applies on its own; open the app to review and send.\nTurn off with: applybot schedule --off")


def cmd_status(args):
    _, _, db = _ctx(args)
    counts = db.status_counts()
    t = Table(title="Pipeline status")
    t.add_column("status")
    t.add_column("jobs", justify="right")
    for s in STATUSES:
        if counts.get(s):
            t.add_row(s, str(counts[s]))
    console.print(t)
    log(f"applications submitted today: {db.applied_today()}")
    apps = db.applications(limit=args.limit if hasattr(args, "limit") else 10)
    if apps:
        a = Table(title="Recent application attempts")
        for col in ("when", "job", "status", "mode", "notes"):
            a.add_column(col, overflow="fold", max_width=60 if col == "notes" else None)
        for r in apps:
            a.add_row(r["created_at"][:16], r["job_id"] or "", r["status"], r["mode"], r["notes"] or "")
        console.print(a)


def cmd_mark(args):
    _, _, db = _ctx(args)
    job = db.get_job(args.job)
    if not job:
        log(f"[red]job {args.job} not found[/red]")
        return 1
    db.update_job(job["id"], status=args.status)
    log(f"{job['id']} -> {args.status}")


def cmd_ask(args):
    cfg, llm, _ = _ctx(args)
    try:
        log(llm.complete(" ".join(args.prompt)))
    except LLMError as e:
        log(f"[red]{e}[/red]")
        return 1


def cmd_ui(args):
    from applybot.ui.launcher import run
    return run(Path(args.config), port=args.port, open_window=not args.no_window)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="applybot", description="Find postings, tailor resumes, and auto-apply.")
    p.add_argument("-c", "--config", default="config.yaml", help="path to config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create config.yaml, profile.txt, answers.yaml, .env templates").set_defaults(fn=cmd_init)

    s = sub.add_parser("profile", help="parse and display your profile")
    s.add_argument("--refresh", action="store_true", help="re-parse even if cached")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_profile)

    s = sub.add_parser("search", help="discover new postings from enabled sources")
    s.add_argument("--source", action="append", help="only this source (repeatable)")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("score", help="score unscored jobs against your profile")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--rescore", action="store_true", help="re-score matched/rejected jobs")
    s.set_defaults(fn=cmd_score)

    s = sub.add_parser("list", help="list tracked jobs")
    s.add_argument("--status", choices=STATUSES)
    s.add_argument("--min-score", type=float)
    s.add_argument("--limit", type=int, default=40)
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("show", help="show one job")
    s.add_argument("job")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("tailor", help="generate a tailored resume (+ cover letter) for job id(s)")
    s.add_argument("jobs", nargs="+")
    s.add_argument("--no-cover", action="store_true")
    s.set_defaults(fn=cmd_tailor)

    s = sub.add_parser("apply", help="apply to job id(s) or ANY application URL")
    s.add_argument("jobs", nargs="*")
    s.add_argument("--url", action="append", help="any application form URL (repeatable)")
    s.add_argument("--company", help="company/organization name for --url")
    s.add_argument("--title", help="position/program title for --url")
    s.add_argument("--mode", choices=["dry_run", "review", "auto"])
    s.add_argument("--headless", action="store_true")
    s.set_defaults(fn=cmd_apply)

    s = sub.add_parser("run", help="full pipeline: search -> score -> tailor -> apply")
    s.add_argument("--mode", choices=["dry_run", "review", "auto"])
    s.add_argument("--max", type=int, help="max applications this run")
    s.add_argument("--score-limit", type=int, default=150, help="max jobs to score this run")
    s.add_argument("--skip-search", action="store_true")
    s.add_argument("--headless", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("refresh", help="search + score only (no applying) - what the daily schedule runs")
    s.add_argument("--score-limit", type=int, default=150)
    s.add_argument("--top", type=int, default=15, help="how many top matches to print")
    s.set_defaults(fn=cmd_refresh)

    s = sub.add_parser("export", help="export jobs.csv and applications.csv for spreadsheets")
    s.add_argument("--out", help="output folder (default: <data folder>/export)")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("schedule", help="run refresh daily via Windows Task Scheduler")
    s.add_argument("time", nargs="?", help="24h time, e.g. 08:45; omit to show the current schedule")
    s.add_argument("--off", action="store_true", help="remove the scheduled task")
    s.set_defaults(fn=cmd_schedule)

    s = sub.add_parser("status", help="pipeline and application summary")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("mark", help="manually set a job's status")
    s.add_argument("job")
    s.add_argument("status", choices=STATUSES)
    s.set_defaults(fn=cmd_mark)

    s = sub.add_parser("ask", help="send a prompt to the configured AI (connectivity test)")
    s.add_argument("prompt", nargs="+")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("ui", help="open the desktop app (default when no command is given)")
    s.add_argument("--port", type=int, default=0, help="port for the local UI server (default: automatic)")
    s.add_argument("--no-window", action="store_true", help="don't open a window; just print the URL")
    s.set_defaults(fn=cmd_ui)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    commands = next(a.choices for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    if not set(argv) & (set(commands) | {"-h", "--help"}):
        argv = [*argv, "ui"]
    args = parser.parse_args(argv)
    try:
        return args.fn(args) or 0
    except FileNotFoundError as e:
        log(f"[red]{e}[/red]")
        return 1
    except KeyboardInterrupt:
        log("\n[yellow]interrupted[/yellow]")
        return 130
