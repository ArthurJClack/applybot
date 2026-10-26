"""Local HTTP server for the ApplyBot UI: a JSON API over the pipeline plus the static single-page app.
Binds to 127.0.0.1 only; API calls must carry an `X-ApplyBot` header (blocks cross-site requests)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import yaml
from rich.markup import escape

from applybot import __version__
from applybot.answers import DEFAULT_ANSWERS
from applybot.config import DEFAULTS, _DOTENV_KEYS, deep_merge, init_workspace, load_config
from applybot.db import DB, STATUSES
from applybot.llm import LLM, LLMError
from applybot.ui.tasks import Busy, Task, TaskManager

STATIC = Path(__file__).parent / "static"
SAMPLE_MARKERS = ("alex.rivera@example.com",)
KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY",
           "openai_compatible": "OPENAI_COMPATIBLE_API_KEY"}
MODES = ("dry_run", "review", "auto")
CTYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
          ".ico": "image/x-icon", ".pdf": "application/pdf", ".json": "application/json; charset=utf-8",
          ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
          ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def browser_installed() -> bool:
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if root == "0":
        return True
    path = Path(root) if root else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
    try:
        return any(p.name.startswith("chromium-") for p in path.iterdir())
    except OSError:
        return False


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - opens with the user's default app
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App:
    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path).resolve()
        self.base_dir = self.config_path.parent
        init_workspace(self.base_dir)
        self.tasks = TaskManager()
        self.tasks.on_prompt = self._attention
        self.attention_hooks: list[Callable[[], None]] = []
        self.last_seen = time.time()
        self.bye_at = 0.0

    # ------------------------------------------------------------------ helpers
    def cfg(self):
        return load_config(self.config_path)

    def ctx(self):
        cfg = self.cfg()
        return cfg, LLM(cfg["ai"]), DB(cfg.path("database"))

    @staticmethod
    def load_profile(cfg, llm, refresh: bool = False) -> dict:
        from applybot.profile import load_profile
        return load_profile(cfg.path("profile", "path"), llm, cfg["profile"].get("parser", "auto"),
                            cfg.path("profile", "cache_path"), refresh=refresh)

    def _attention(self):
        if sys.platform == "win32":
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        for hook in self.attention_hooks:
            try:
                hook()
            except Exception:
                pass

    def rel(self, p: Path) -> str:
        p = Path(p).resolve()
        try:
            return p.relative_to(self.base_dir).as_posix()
        except ValueError:
            return p.as_posix()

    def safe_path(self, raw: str) -> Path | None:
        """Resolve a path from the UI, allowing only files inside the data folder or the output folder."""
        p = Path(raw)
        if not p.is_absolute():
            p = self.base_dir / p
        p = p.resolve()
        roots = [self.base_dir]
        try:
            roots.append(self.cfg().path("apply", "output_dir").resolve())
        except Exception:
            pass
        return p if any(p == r or p.is_relative_to(r) for r in roots) else None

    def read_user_config(self) -> dict:
        if not self.config_path.exists():
            return {}
        return yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}

    def set_env_var(self, name: str, value: str) -> None:
        env = self.base_dir / ".env"
        lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
        out, done = [], False
        for line in lines:
            if re.match(rf"^\s*{re.escape(name)}\s*=", line):
                if not done:
                    out.append(f"{name}={value}")
                    done = True
                continue
            out.append(line)
        if not done:
            out.append(f"{name}={value}")
        env.write_text("\n".join(out) + "\n", encoding="utf-8")
        os.environ[name] = value
        _DOTENV_KEYS.add(name)

    def start(self, kind: str, name: str, fn: Callable[[Task], Any]):
        try:
            task = self.tasks.start(name, kind, fn)
        except Busy as e:
            return 409, {"error": f"Another task is running: {e}"}
        return 200, {"task": task.summary()}

    # ------------------------------------------------------------------ routing
    def route(self, method: str, path: str, q: dict, body: dict) -> tuple[int, Any]:
        table = {
            ("GET", "/api/ping"): lambda: (200, {"app": "applybot", "version": __version__}),
            ("GET", "/api/state"): self.api_state,
            ("GET", "/api/jobs"): lambda: self.api_jobs(q),
            ("GET", "/api/job"): lambda: self.api_job(q.get("id", "")),
            ("GET", "/api/applications"): lambda: self.api_applications(int(q.get("limit") or 100)),
            ("GET", "/api/task"): lambda: self.api_task(q),
            ("GET", "/api/file"): lambda: self.api_file_get(q.get("name", "")),
            ("GET", "/api/profile/parsed"): lambda: self.api_profile_parsed(q.get("refresh") == "1"),
            ("GET", "/api/answers"): self.api_answers_get,
            ("GET", "/api/settings"): self.api_settings_get,
            ("POST", "/api/jobs/mark"): lambda: self.api_mark(body),
            ("POST", "/api/task/answer"): lambda: self.api_task_answer(body),
            ("POST", "/api/task/stop"): self.api_task_stop,
            ("POST", "/api/file"): lambda: self.api_file_post(body),
            ("POST", "/api/answers"): lambda: self.api_answers_post(body),
            ("POST", "/api/settings"): lambda: self.api_settings_post(body),
            ("POST", "/api/ai/test"): self.api_ai_test,
            ("POST", "/api/open"): lambda: self.api_open(body),
        }
        fn = table.get((method, path))
        if fn:
            return fn()
        if method == "POST" and path.startswith("/api/tasks/"):
            return self.api_start_task(path.rsplit("/", 1)[-1], body)
        return 404, {"error": f"unknown endpoint {method} {path}"}

    # ------------------------------------------------------------------ dashboard state
    def api_state(self):
        from applybot.profile import parse_structured
        cfg = self.cfg()
        llm = LLM(cfg["ai"])
        db = DB(cfg.path("database"))
        try:
            counts = db.status_counts()
            applied_today = db.applied_today()
            total_applied = db.conn.execute("SELECT COUNT(*) FROM applications WHERE status='applied'").fetchone()[0]
            sources = [r[0] for r in db.conn.execute("SELECT DISTINCT source FROM jobs ORDER BY source")]
            new_today = db.conn.execute("SELECT COUNT(*) FROM jobs WHERE substr(created_at,1,10)=date('now')"
                                        ).fetchone()[0]
        finally:
            db.close()
        ppath = cfg.path("profile", "path")
        ptext = ppath.read_text(encoding="utf-8") if ppath.exists() else ""
        name = ""
        try:
            name = parse_structured(ptext).get("contact", {}).get("name", "") if ptext.strip() else ""
        except Exception:
            pass
        sample = any(m in ptext for m in SAMPLE_MARKERS)
        total = sum(counts.values())
        return 200, {
            "version": __version__, "data_dir": str(self.base_dir),
            "counts": counts, "total": total, "applied_today": applied_today, "total_applied": total_applied,
            "new_today": new_today, "sources": sources, "name": name,
            "ai": {"provider": llm.provider, "model": llm.model, "available": llm.available},
            "apply": {k: cfg["apply"].get(k) for k in ("mode", "headless", "max_per_run", "max_per_day")},
            "min_score": cfg["matching"].get("min_score", 60),
            "setup": {"profile": bool(ptext.strip()) and not sample, "sample_profile": sample,
                      "ai": llm.available, "ai_off": llm.provider == "none", "ai_reason": llm.unavailable_reason(),
                      "browser": browser_installed(), "jobs": total > 0},
            "task": self.tasks.current.summary() if self.tasks.current else None,
        }

    # ------------------------------------------------------------------ jobs
    def api_jobs(self, q: dict):
        cfg = self.cfg()
        db = DB(cfg.path("database"))
        try:
            where, args = [], []
            if q.get("q"):
                like = f"%{q['q'].strip()}%"
                where.append("(company LIKE ? OR title LIKE ? OR location LIKE ?)")
                args += [like, like, like]
            if q.get("source"):
                where.append("source = ?")
                args.append(q["source"])
            if q.get("min_score"):
                where.append("score >= ?")
                args.append(float(q["min_score"]))
            base = " AND ".join(where) or "1=1"
            tab_counts = {r[0]: r[1] for r in db.conn.execute(
                f"SELECT status, COUNT(*) FROM jobs WHERE {base} GROUP BY status", args)}
            status = q.get("status")
            if status:
                base += " AND status = ?"
                args.append(status)
            order = {"score": "score IS NULL, score DESC, posted_at DESC", "newest": "posted_at DESC",
                     "company": "company COLLATE NOCASE, title", "updated": "updated_at DESC"
                     }.get(q.get("sort") or "score", "score IS NULL, score DESC")
            limit = max(1, min(int(q.get("limit") or 300), 3000))
            total = db.conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {base}", args).fetchone()[0]
            rows = db.conn.execute(
                "SELECT id, company, title, location, source, posted_at, score, status, job_type, remote, url, "
                f"apply_url, created_at, updated_at FROM jobs WHERE {base} ORDER BY {order} LIMIT ?",
                [*args, limit]).fetchall()
            return 200, {"jobs": [dict(r) for r in rows], "total": total, "tab_counts": tab_counts}
        finally:
            db.close()

    def api_job(self, jid: str):
        from applybot.pipeline import job_dir
        cfg = self.cfg()
        db = DB(cfg.path("database"))
        try:
            job = db.get_job(jid) if jid else None
            if not job:
                return 404, {"error": "job not found"}
            apps = [dict(r) for r in db.conn.execute(
                "SELECT id, status, mode, notes, url, created_at FROM applications WHERE job_id=? ORDER BY id DESC",
                (job["id"],))]
        finally:
            db.close()
        d = job_dir(cfg, job, create=False)
        docs = []
        if d.exists():
            for f in sorted(d.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if f.is_file() and f.suffix.lower() in (".pdf", ".docx", ".png", ".txt", ".md"):
                    docs.append({"name": f.name, "path": self.rel(f), "size": f.stat().st_size,
                                 "ext": f.suffix.lower()[1:], "mtime": f.stat().st_mtime})
        job["docs"] = docs
        job["doc_dir"] = self.rel(d) if d.exists() else None
        job["applications"] = apps
        return 200, job

    def api_mark(self, body: dict):
        status = body.get("status")
        if status not in STATUSES:
            return 400, {"error": f"invalid status {status!r}"}
        cfg = self.cfg()
        db = DB(cfg.path("database"))
        try:
            for jid in body.get("ids") or []:
                db.update_job(jid, status=status)
        finally:
            db.close()
        return 200, {"ok": True}

    def api_applications(self, limit: int):
        cfg = self.cfg()
        db = DB(cfg.path("database"))
        try:
            rows = db.conn.execute(
                "SELECT a.id, a.job_id, a.url, a.status, a.mode, a.notes, a.created_at, j.company, j.title "
                "FROM applications a LEFT JOIN jobs j ON j.id = a.job_id ORDER BY a.id DESC LIMIT ?",
                (max(1, min(limit, 1000)),)).fetchall()
            return 200, {"applications": [dict(r) for r in rows]}
        finally:
            db.close()

    # ------------------------------------------------------------------ tasks
    def api_task(self, q: dict):
        t = self.tasks.current
        if t is None:
            return 200, {"task": None, "lines": [], "count": 0}
        since = int(q.get("since") or 0) if q.get("id") == t.id else 0
        count, lines = t.lines_since(since)
        return 200, {"task": t.summary(), "lines": lines, "count": count}

    def api_task_answer(self, body: dict):
        t = self.tasks.current
        ok = bool(t and t.answer(str(body.get("id")), body.get("value")))
        return (200, {"ok": True}) if ok else (409, {"error": "that question is no longer waiting"})

    def api_task_stop(self):
        t = self.tasks.current
        if t and t.status == "running":
            t.stop()
        return 200, {"ok": True}

    def api_start_task(self, kind: str, body: dict):
        mode = body.get("mode")
        if mode is not None and mode not in MODES:
            return 400, {"error": f"invalid mode {mode!r}"}
        if kind == "search":
            return self.start(kind, "Finding new jobs", lambda t: self.t_search(t, body.get("sources")))
        if kind == "score":
            return self.start(kind, "Scoring jobs", lambda t: self.t_score(
                t, int(body.get("limit") or 300), bool(body.get("rescore"))))
        if kind == "tailor":
            ids = body.get("ids") or []
            if not ids:
                return 400, {"error": "no jobs selected"}
            return self.start(kind, f"Tailoring documents ({len(ids)})", lambda t: self.t_tailor(t, ids))
        if kind == "apply":
            ids = body.get("ids") or []
            if not ids:
                return 400, {"error": "no jobs selected"}
            return self.start(kind, f"Applying ({len(ids)}, {mode or 'default mode'})",
                              lambda t: self.t_apply(t, ids, mode, body.get("headless")))
        if kind == "apply_url":
            url = (body.get("url") or "").strip()
            if not re.match(r"^https?://", url):
                return 400, {"error": "enter a full URL starting with http:// or https://"}
            manual = {k: (body.get(k) or "").strip() for k in ("url", "company", "title", "description")}
            return self.start(kind, f"Applying to {urlparse(url).netloc}",
                              lambda t: self.t_apply(t, [], mode, body.get("headless"), manual))
        if kind == "run":
            return self.start(kind, f"Autopilot ({mode or 'default mode'})", lambda t: self.t_run(t, body))
        if kind == "install_browser":
            return self.start(kind, "Installing browser", self.t_install_browser)
        return 404, {"error": f"unknown task {kind}"}

    @staticmethod
    def _asker(t: Task):
        def ask(field):
            t.log(f"[yellow]Waiting for your answer: {escape(field.question)}[/yellow]")
            val = t.ask({"kind": "field", "title": "A required question needs your answer",
                         "message": field.question, "options": field.options or [], "field_kind": field.kind,
                         "required": field.required})
            if val is None:
                return None
            val = str(val).strip()
            return val or None
        return ask

    @staticmethod
    def _pauser(t: Task):
        def pause(message: str, choices, details):
            t.log(f"[yellow]Waiting for you: {escape(message)}[/yellow]")
            det = None
            if details:
                det = {"answers": {str(k): str(v)[:400] for k, v in (details.get("answers") or {}).items()},
                       "unresolved": [str(x) for x in details.get("unresolved") or []]}
            return t.ask({"kind": "choice", "title": "Your turn", "message": message,
                          "choices": [{"value": v, "label": label} for v, label in choices],
                          "details": det}) or ""
        return pause

    def t_search(self, t: Task, sources):
        from applybot.matcher import discover
        cfg, _, db = self.ctx()
        try:
            t.log("[bold]Searching job sources...[/bold]")
            stats = discover(cfg, db, log=t.log, only=sources or None)
            t.log(f"\n[bold green]{stats['new']} new job(s)[/bold green] saved "
                  f"({stats['kept']} matched your filters out of {stats['fetched']} fetched)")
            return stats
        finally:
            db.close()

    def t_score(self, t: Task, limit: int, rescore: bool):
        from applybot.matcher import score_jobs
        cfg, llm, db = self.ctx()
        try:
            if rescore:
                db.conn.execute("UPDATE jobs SET score=NULL, status='new' WHERE status IN ('matched','rejected')")
                db.conn.commit()
            profile = self.load_profile(cfg, llm)
            t.log("[bold]Scoring jobs against your profile...[/bold]")
            n = score_jobs(db, profile, llm, cfg, limit=limit, log=t.log)
            t.log(f"\n[bold green]Scored {n} job(s)[/bold green]")
            return {"scored": n}
        finally:
            db.close()

    def t_tailor(self, t: Task, ids: list[str]):
        from applybot.pipeline import prepare_documents
        cfg, llm, db = self.ctx()
        try:
            profile = self.load_profile(cfg, llm)
            done = 0
            for jid in ids:
                job = db.get_job(jid)
                if not job:
                    t.log(f"[red]job {escape(jid)} not found[/red]")
                    continue
                t.log(f"[bold]{escape(job['company'])} - {escape(job['title'])}[/bold]")
                prepare_documents(cfg, profile, llm, job, db, t.log)
                if job["status"] in ("new", "matched"):
                    db.update_job(job["id"], status="tailored")
                done += 1
            t.log(f"\n[bold green]Tailored documents for {done} job(s)[/bold green]")
            return {"tailored": done}
        finally:
            db.close()

    def t_apply(self, t: Task, ids: list[str], mode: str | None, headless, manual: dict | None = None):
        from applybot.pipeline import apply_jobs, manual_job
        cfg, llm, db = self.ctx()
        try:
            mode = mode or cfg["apply"]["mode"]
            if headless is not None:
                cfg["apply"]["headless"] = bool(headless)
            profile = self.load_profile(cfg, llm)
            jobs = []
            if manual:
                mj = manual_job(manual["url"], manual.get("company", ""), manual.get("title", ""),
                                manual.get("description", ""))
                db.upsert_job(mj)
                jobs.append(db.get_job(mj.id) or {**mj.to_dict(), "status": "new"})
            for jid in ids:
                job = db.get_job(jid)
                if job:
                    jobs.append(job)
                else:
                    t.log(f"[red]job {escape(jid)} not found[/red]")
            if not jobs:
                t.log("Nothing to apply to.")
                return {}
            t.log(f"[bold]Applying to {len(jobs)} job(s) - mode: {mode}[/bold]")
            results = apply_jobs(cfg, db, profile, llm, jobs, mode, t.log,
                                 ask_human=self._asker(t), pause=self._pauser(t))
            tally: dict[str, int] = {}
            for r in results:
                tally[r["result"].status] = tally.get(r["result"].status, 0) + 1
            t.log("\n[bold green]Finished:[/bold green] " + (", ".join(f"{v} {k}" for k, v in tally.items())
                                                            or "nothing processed"))
            return tally
        finally:
            db.close()

    def t_run(self, t: Task, body: dict):
        from applybot.matcher import discover, score_jobs
        from applybot.pipeline import apply_jobs
        cfg, llm, db = self.ctx()
        try:
            mode = body.get("mode") or cfg["apply"]["mode"]
            if body.get("headless") is not None:
                cfg["apply"]["headless"] = bool(body["headless"])
            profile = self.load_profile(cfg, llm)
            if not body.get("skip_search"):
                t.log("[bold]Step 1 - Searching for postings[/bold]")
                stats = discover(cfg, db, log=t.log)
                t.log(f"[green]{stats['new']} new job(s)[/green]")
            t.log("\n[bold]Step 2 - Scoring fit[/bold]")
            score_jobs(db, profile, llm, cfg, limit=int(body.get("score_limit") or 300), log=t.log)
            limit = int(body.get("max") or cfg["apply"].get("max_per_run", 10))
            min_score = float(cfg["matching"].get("min_score", 60))
            targets = db.list_jobs(status="matched", min_score=min_score, limit=limit)
            t.log(f"\n[bold]Step 3 - {len(targets)} top match(es) selected[/bold] (score >= {min_score:.0f})")
            for j in targets:
                t.log(f"  {j['score']:.0f}  {escape(j['company'])} - {escape(j['title'])}")
            if not targets:
                t.log("No matched jobs to apply to right now.")
                return {}
            t.log(f"\n[bold]Step 4 - Applying (mode: {mode})[/bold]")
            results = apply_jobs(cfg, db, profile, llm, targets, mode, t.log,
                                 ask_human=self._asker(t), pause=self._pauser(t))
            tally: dict[str, int] = {}
            for r in results:
                tally[r["result"].status] = tally.get(r["result"].status, 0) + 1
            t.log("\n[bold green]Autopilot finished:[/bold green] " + ", ".join(f"{v} {k}" for k, v in tally.items()))
            return tally
        finally:
            db.close()

    @staticmethod
    def t_install_browser(t: Task):
        from applybot.apply.browser import install_browser
        if not install_browser(t.log):
            raise RuntimeError("browser installation failed")
        return {"ok": True}

    # ------------------------------------------------------------------ files / profile / answers
    def _file_path(self, name: str) -> Path | None:
        if name == "config":
            return self.config_path
        cfg = self.cfg()
        if name == "profile":
            return cfg.path("profile", "path")
        if name == "answers":
            return cfg.path("profile", "answers_path")
        return None

    def api_file_get(self, name: str):
        p = self._file_path(name)
        if p is None:
            return 404, {"error": "unknown file"}
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        return 200, {"name": name, "path": str(p), "text": text,
                     "sample": name == "profile" and any(m in text for m in SAMPLE_MARKERS)}

    def api_file_post(self, body: dict):
        name, text = body.get("name", ""), body.get("text")
        p = self._file_path(name)
        if p is None or not isinstance(text, str):
            return 400, {"error": "bad request"}
        if name in ("config", "answers"):
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError as e:
                return 400, {"error": f"YAML error: {e}"}
            if data is not None and not isinstance(data, dict):
                return 400, {"error": "the file must be a YAML mapping (key: value)"}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return 200, {"ok": True}

    def api_profile_parsed(self, refresh: bool):
        from applybot.profile import all_skills
        cfg = self.cfg()
        llm = LLM(cfg["ai"])
        try:
            p = self.load_profile(cfg, llm, refresh=refresh)
        except (FileNotFoundError, LLMError) as e:
            return 200, {"error": str(e)}
        out = {k: v for k, v in p.items() if k != "raw"}
        out["all_skills"] = all_skills(p)
        return 200, out

    def api_answers_get(self):
        p = self.cfg().path("profile", "answers_path")
        data = {}
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                return 200, {"error": f"answers.yaml has a YAML error: {e}", "data": DEFAULT_ANSWERS}
        merged = deep_merge(DEFAULT_ANSWERS, data)
        for k in ("custom", "learned"):
            if not isinstance(merged.get(k), dict):
                merged[k] = {}
        return 200, {"data": merged, "path": str(p)}

    def api_answers_post(self, body: dict):
        data = body.get("data")
        if not isinstance(data, dict):
            return 400, {"error": "bad request"}
        p = self.cfg().path("profile", "answers_path")
        header = ("# Answers to common application questions (edited in the ApplyBot app).\n"
                  "# ApplyBot never lets the AI guess legal, work-authorization, or demographic answers.\n")
        p.write_text(header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000),
                     encoding="utf-8")
        return 200, {"ok": True}

    # ------------------------------------------------------------------ settings
    def api_settings_get(self):
        user = self.read_user_config()
        merged = deep_merge(DEFAULTS, user)
        cfg = self.cfg()
        ai = merged["ai"]
        key = str(cfg["ai"].get("api_key") or "")
        return 200, {
            "ai": {"provider": ai.get("provider"), "model": ai.get("model"), "base_url": ai.get("base_url") or "",
                   "command": ai.get("command") or "", "key_set": bool(key),
                   "key_hint": ("..." + key[-4:]) if len(key) > 8 else ("set" if key else ""),
                   "key_env": KEY_ENV.get(str(ai.get("provider")))},
            "key_status": {p: bool(os.environ.get(env)) for p, env in KEY_ENV.items()},
            "search": merged["search"], "matching": merged["matching"], "apply": merged["apply"],
            "data_dir": str(self.base_dir), "config_path": str(self.config_path),
            "browser_installed": browser_installed(),
        }

    def api_settings_post(self, body: dict):
        user = self.read_user_config()
        ai_in = dict(body.get("ai") or {})
        api_key = str(ai_in.pop("api_key", "") or "").strip()
        ai = dict(user.get("ai") or {})
        for k in ("provider", "model", "base_url", "command"):
            if k in ai_in:
                v = ai_in[k]
                ai[k] = (v.strip() or None) if isinstance(v, str) else v
        provider = ai.get("provider") or DEFAULTS["ai"]["provider"]
        env = KEY_ENV.get(provider)
        current = str(ai.get("api_key") or "")
        if env and (api_key or not current or current.startswith("${")):
            ai["api_key"] = "${" + env + "}"
        if api_key and env:
            self.set_env_var(env, api_key)
        user["ai"] = ai
        for section in ("search", "matching", "apply"):
            if isinstance(body.get(section), dict):
                user[section] = deep_merge(user.get(section) or {}, body[section])
        text = ("# ApplyBot configuration (edited in the ApplyBot app). See README.md for every option.\n"
                + yaml.safe_dump(user, sort_keys=False, allow_unicode=True, default_flow_style=None, width=110))
        yaml.safe_load(text)
        self.config_path.write_text(text, encoding="utf-8")
        return 200, {"ok": True}

    def api_ai_test(self):
        cfg = self.cfg()
        cfg["ai"]["timeout"] = 45
        llm = LLM(cfg["ai"])
        if not llm.available:
            return 200, {"ok": False, "error": f"AI provider '{llm.provider}' is not configured"
                         + (" (no API key saved)" if llm.provider in KEY_ENV else "")}
        t0 = time.time()
        try:
            reply = llm.complete("Reply with exactly the word OK.", max_tokens=20)
        except Exception as e:
            return 200, {"ok": False, "error": str(e)[:500]}
        return 200, {"ok": True, "reply": reply.strip()[:200], "seconds": round(time.time() - t0, 1),
                     "provider": llm.provider, "model": llm.model}

    def api_open(self, body: dict):
        if body.get("url"):
            url = str(body["url"])
            if not re.match(r"^https?://", url):
                return 400, {"error": "only web links can be opened"}
            webbrowser.open(url)
            return 200, {"ok": True}
        raw = body.get("path") or ""
        p = self.base_dir if raw in ("", "data_dir") else self.safe_path(raw)
        if p is None or not p.exists():
            return 404, {"error": "file not found"}
        open_path(p)
        return 200, {"ok": True}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "ApplyBot"

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code: int, obj: Any):
            self._send(code, json.dumps(obj, default=str).encode("utf-8"), "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in ("127.0.0.1", "localhost")

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method: str):
            body_raw = b""
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                body_raw = self.rfile.read(n) if n else b""
            if not self._host_ok():
                return self._json(403, {"error": "forbidden"})
            u = urlparse(self.path)
            path = u.path
            q = {k: v[-1] for k, v in parse_qs(u.query).items()}
            try:
                if path.startswith("/api/"):
                    if path == "/api/bye" and method == "POST":
                        app.bye_at = time.time()
                        return self._json(200, {"ok": True})
                    if self.headers.get("X-ApplyBot") != "1":
                        return self._json(403, {"error": "forbidden"})
                    app.last_seen = time.time()
                    body = json.loads(body_raw or b"{}") if method == "POST" else {}
                    code, obj = app.route(method, path, q, body if isinstance(body, dict) else {})
                    return self._json(code, obj)
                if method == "GET" and path.startswith("/files/"):
                    return self._file(unquote(path[len("/files/"):]))
                if method == "GET":
                    return self._static(path)
                return self._json(404, {"error": "not found"})
            except Exception as e:
                traceback.print_exc()
                try:
                    return self._json(500, {"error": f"{type(e).__name__}: {e}"})
                except Exception:
                    pass

        def _file(self, raw: str):
            p = app.safe_path(raw)
            if p is None or not p.is_file():
                return self._json(404, {"error": "not found"})
            ctype = CTYPES.get(p.suffix.lower(), "application/octet-stream")
            self._send(200, p.read_bytes(), ctype, {"Content-Disposition": f'inline; filename="{p.name}"'})

        def _static(self, path: str):
            name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
            p = (STATIC / name).resolve()
            if not p.is_relative_to(STATIC.resolve()) or not p.is_file():
                p = STATIC / "index.html"  # single-page app fallback
            self._send(200, p.read_bytes(), CTYPES.get(p.suffix.lower(), "application/octet-stream"))

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def make_server(app: App, port: int = 0) -> Server:
    handler = make_handler(app)
    try:
        return Server(("127.0.0.1", port), handler)
    except OSError:
        return Server(("127.0.0.1", 0), handler)
