"""Local bridge between the ApplyBot browser extension and ApplyBot's answers, documents and job tracker.

The extension reports the form it sees; the bridge answers with what to fill. Claude (through the MCP tools in
applybot.live.tools) can read the live form and push edits to it. Listens on 127.0.0.1 only.
"""
from __future__ import annotations

import json
import re
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from applybot.answers import SENSITIVE_PREFIXES, AnswerBank, Field, choose_option, classify, resolve_fields

DEFAULT_PORT = 8765
FILE_KINDS = {"resume": "resume", "cover_letter": "cover_letter"}
_ID_RE = re.compile(r"(\d{6,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-F0-9]{10})")
_ALLOWED_ORIGIN = re.compile(r"^((moz|chrome)-extension://|http://(127\.0\.0\.1|localhost):\d+$)")
# Questions that ask for LINKS (a portfolio, project URLs) - not essay questions that merely mention projects.
PROJECT_LINKS_RE = re.compile(r"portfolio|work samples?|other (links|urls?|websites?)|links? to (your )?(work|projects?)|"
                              r"project (links?|urls?)|github|(links?|urls?|website)\b.*\bprojects?|projects?\b.*\b(links?|urls?)", re.I)
ESSAYISH_RE = re.compile(r"^(what|why|how|describe|tell|explain|share|please describe|briefly)\b|\?\s*$", re.I)
DASHBOARD = Path(__file__).parent / "dashboard.html"


def url_tokens(url: str) -> list[str]:
    """Stable id-looking pieces of a job URL (greenhouse job number, lever/ashby uuid, workable code)."""
    return _ID_RE.findall(url or "")


def form_url(url: str) -> str:
    """Company career pages that embed Greenhouse (...?gh_jid=123) load the form late or not at all; Greenhouse's
    own embed page for that job number is the same form, every time."""
    m = re.search(r"[?&]gh_jid=(\d+)", url or "")
    if m and "greenhouse.io" not in url:
        return f"https://boards.greenhouse.io/embed/job_app?token={m.group(1)}"
    # boards.greenhouse.io/<board>/jobs/<id> often redirects to the company's own careers site; the embed doesn't
    m = re.match(r"https?://boards\.greenhouse\.io/(?!embed/)([^/?#]+)/jobs/(\d+)", url or "")
    if m:
        return f"https://boards.greenhouse.io/embed/job_app?for={m.group(1)}&token={m.group(2)}"
    return url


def is_sensitive(category: str | None) -> bool:
    return bool(category) and (category == "consent" or category.startswith(SENSITIVE_PREFIXES))


def open_in_new_window(url: str) -> bool:
    """Open `url` in a NEW Firefox window (so ApplyBot's jobs stay out of your everyday window), else the
    default browser. Later jobs in the queue reuse that window's tab."""
    import os
    import shutil
    import subprocess
    candidates = [shutil.which("firefox"),
                  os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Mozilla Firefox", "firefox.exe"),
                  os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), "Mozilla Firefox", "firefox.exe"),
                  "/Applications/Firefox.app/Contents/MacOS/firefox"]
    for exe in candidates:
        if exe and os.path.exists(exe):
            try:
                subprocess.Popen([exe, "-new-window", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                continue
    return webbrowser.open_new(url)


class LiveBridge:
    """State shared by the HTTP handler (the extension) and the MCP tools (Claude)."""

    def __init__(self, context: Callable[[], tuple], opener: Callable[[str], object] = open_in_new_window):
        self._context = context          # () -> (cfg, profile, db)
        self._open = opener
        self.lock = threading.RLock()
        self.pages: dict[str, dict] = {}        # tab id -> last reported page
        self.commands: dict[str, list] = {}     # tab id -> pending live edits
        self.pending: dict[str, dict] = {}      # tab id -> answers captured at submit, waiting for confirmation
        self.queue: list[str] = []              # job ids still to open
        self.expected: str | None = None        # job id the next ATS page most likely belongs to
        self.log: list[str] = []
        self.last_seen = 0.0
        self.server: ThreadingHTTPServer | None = None
        self.port = DEFAULT_PORT
        self.auto_submit: bool | None = None    # None = use config live.auto_submit
        self.ext_reload = False                 # ask the Firefox extension to reload itself (picks up new code)

    # ---- helpers -------------------------------------------------------------------------------------------
    def _note(self, msg: str):
        with self.lock:
            self.log.append(time.strftime("%H:%M:%S ") + msg)
            del self.log[:-200]

    def find_job(self, db, url: str) -> dict | None:
        row = db.conn.execute("SELECT id FROM jobs WHERE apply_url=? OR url=? LIMIT 1", (url, url)).fetchone()
        if not row:
            for tok in url_tokens(url):
                rows = db.conn.execute("SELECT id FROM jobs WHERE apply_url LIKE ? OR url LIKE ? LIMIT 2",
                                       (f"%{tok}%", f"%{tok}%")).fetchall()
                if len(rows) == 1:
                    row = rows[0]
                    break
        if row:
            return db.get_job(row[0])
        if self.expected:
            return db.get_job(self.expected)
        return None

    @staticmethod
    def project_links(bank: AnswerBank, profile: dict) -> list[str]:
        saved = bank.data.get("project_links")
        if saved:
            return [str(x) for x in saved]
        c = profile.get("contact", {})
        return [x for x in (c.get("website"), c.get("github")) if x]

    def save_project_links(self, links: list[str]) -> dict:
        cfg, profile, _ = self._context()
        bank = AnswerBank(cfg.path("profile", "answers_path"), profile)
        bank.data["project_links"] = [str(x).strip() for x in links if str(x).strip()]
        bank.save()
        return {"project_links": bank.data["project_links"]}

    def documents(self, cfg, job: dict | None) -> dict[str, Path]:
        """The tailored resume / cover letter for this job, falling back to the newest ones anywhere."""
        from applybot.pipeline import job_dir
        out: dict[str, Path] = {}
        dirs = [job_dir(cfg, job, create=False)] if job else []
        for kind, pattern in (("resume", "*Resume*.pdf"), ("cover_letter", "*Cover_Letter*.pdf")):
            for d in dirs:
                hits = sorted(d.glob(pattern)) if d.exists() else []
                if hits:
                    out[kind] = hits[0]
                    break
        if "resume" not in out:  # not tailored for this job: your standard resume, built from your profile
            base = self.base_resume(cfg)
            if base:
                out["resume"] = base
        return out

    def base_resume(self, cfg) -> Path | None:
        """Your untailored resume as a PDF (rebuilt when profile.txt changes), for jobs nobody tailored one for."""
        try:
            from applybot.pipeline import slug
            from applybot.profile import split_name
            from applybot.render import render_pdf
            from applybot.tailor import base_resume
            _, profile, _ = self._context()
            first, last = split_name(profile)
            who = slug(f"{first}_{last}", 40) if first else "Candidate"
            out = cfg.path("apply", "output_dir") / "_standard"
            pdf = out / f"{who}_Resume.pdf"
            try:
                prof = cfg.path("profile", "path")
            except (KeyError, TypeError):
                prof = None
            stale = not pdf.exists() or (prof is not None and prof.exists() and prof.stat().st_mtime > pdf.stat().st_mtime)
            if stale:
                out.mkdir(parents=True, exist_ok=True)
                render_pdf(base_resume(profile), pdf)
            return pdf
        except Exception as e:  # never break filling over the fallback
            self._note(f"couldn't build your standard resume: {e}")
            return None

    # ---- extension-facing ----------------------------------------------------------------------------------
    def page(self, tab: str, data: dict) -> dict:
        """The extension saw a form: work out what to fill."""
        cfg, profile, db = self._context()
        url = data.get("url", "")
        job = self.find_job(db, url)
        docs = self.documents(cfg, job)
        cover_text = ""
        bank = AnswerBank(cfg.path("profile", "answers_path"), profile, cover_letter_text=cover_text)
        fields = [Field(key=f["key"], kind=f.get("kind", "text"), label=f.get("label", ""),
                        required=bool(f.get("required")), options=f.get("options") or None,
                        name=f.get("name", ""), placeholder=f.get("placeholder", ""))
                  for f in data.get("fields", []) if f.get("kind") != "password"]
        resolved = resolve_fields(fields, bank, profile, job or {}, None)
        links = self.project_links(bank, profile)
        for f in fields:
            q = f.question or ""
            asks_links = PROJECT_LINKS_RE.search(q) and (not ESSAYISH_RE.search(q.strip()) or re.search(r"links?|urls?", q, re.I))
            if links and f.kind in ("text", "textarea", "url") and asks_links:
                one_line = f.kind != "textarea"
                resolved[f.key].value = (", " if one_line else "\n").join(links)
                resolved[f.key].source = "saved"
        fill, unresolved = [], []
        for f in fields:
            r = resolved[f.key]
            if f.kind == "file":
                kind = "cover_letter" if r.category == "cover_letter" else "resume" if r.category == "resume_file" else None
                if kind and kind in docs and job:
                    fill.append({"key": f.key, "file": f"/live/file/{job['id']}/{kind}", "filename": docs[kind].name,
                                 "source": "document"})
                elif f.required:
                    unresolved.append(f.key)
                continue
            value = r.value
            if value and f.options and f.kind in ("select", "radio", "checkbox_group"):
                value = choose_option(value, f.options)
            if value:
                fill.append({"key": f.key, "value": value, "source": r.source})
            elif f.required:
                unresolved.append(f.key)
        with self.lock:
            self.last_seen = time.time()
            self.pages[tab] = {"tab": tab, "ts": time.time(), "url": url, "title": data.get("title", ""), "job": job and job["id"],
                               "fields": data.get("fields", []), "unresolved": unresolved,
                               "categories": {f.key: resolved[f.key].category for f in fields},
                               "filled": {x["key"]: x.get("value", x.get("filename", "")) for x in fill}}
            if job and self.expected == job["id"]:
                self.expected = None
        self._note(f"form on {urlparse(url).netloc}: {len(fill)} to fill, {len(unresolved)} need an answer")
        auto = self.auto_submit if self.auto_submit is not None else bool((cfg.get("live") or {}).get("auto_submit"))
        return {"job": job and {"id": job["id"], "company": job["company"], "title": job["title"]},
                "already_applied": bool(job) and job.get("status") == "applied",
                "fill": fill, "unresolved": unresolved,
                "auto_submit": auto and bool(job) and job.get("status") != "applied",   # never twice
                "queue_tab": bool(job) and job["id"] == self.expected}

    def state(self, tab: str, data: dict) -> dict:
        """The extension reports current field values (after filling or after you typed something)."""
        with self.lock:
            self.last_seen = time.time()
            page = self.pages.get(tab)
            if page:
                values = {f["key"]: f.get("value") for f in data.get("fields", [])}
                for f in page["fields"]:
                    if f["key"] in values:
                        f["value"] = values[f["key"]]
                page["unresolved"] = [f["key"] for f in page["fields"]
                                      if f.get("required") and not f.get("value") and f.get("kind") != "password"]
        return {"ok": True}

    def take_commands(self, tab: str) -> dict:
        with self.lock:
            self.last_seen = time.time()
            return {"commands": self.commands.pop(tab, [])}

    def submitted(self, tab: str, data: dict) -> dict:
        """You clicked submit: remember what was on the form until the confirmation page shows up."""
        with self.lock:
            self.pending[tab] = {"url": data.get("url", ""), "answers": data.get("answers", []),
                                 "job": (self.pages.get(tab) or {}).get("job"),
                                 "filled": dict((self.pages.get(tab) or {}).get("filled", {}))}
        return {"ok": True}

    def confirmed(self, tab: str, data: dict) -> dict:
        """The confirmation page appeared: mark the job applied, learn your manual answers, open the next job."""
        with self.lock:
            pend = self.pending.pop(tab, None)
        learned: list[str] = []
        job_id = pend and pend.get("job")
        if pend:
            cfg, profile, db = self._context()
            bank = AnswerBank(cfg.path("profile", "answers_path"), profile)
            for a in pend["answers"]:
                q, v, kind = (a.get("label") or "").strip(), a.get("value"), a.get("kind", "text")
                if not q or not v or kind in ("file", "password") or a.get("key") in pend["filled"]:
                    continue
                if classify(q, kind) == "consent" or len(str(v)) > 600:
                    continue  # agreeing to terms is decided per form, never replayed
                if bank.saved_answer(q) != str(v):
                    bank.learn(q, str(v))
                    learned.append(q)
            if job_id:
                db.update_job(job_id, status="applied")
                db.log_application(job_id, pend["url"], "applied", "live", notes="submitted by you (live apply)")
            self._note(f"applied{' to ' + job_id if job_id else ''}; learned {len(learned)} answer(s)")
        return {"applied": job_id, "learned": learned, "next": self.next_url()}

    def next_url(self) -> str | None:
        with self.lock:
            if not self.queue:
                return None
            job_id = self.queue.pop(0)
        _, _, db = self._context()
        job = db.get_job(job_id)
        if not job or job.get("status") == "applied":  # gone, or already sent from another tab
            return self.next_url()
        with self.lock:
            self.expected = job["id"]
        return form_url(job.get("apply_url") or job.get("url"))

    def file_bytes(self, job_id: str, kind: str) -> tuple[bytes, str] | None:
        if kind not in FILE_KINDS:
            return None
        cfg, _, db = self._context()
        job = db.get_job(job_id)
        path = self.documents(cfg, job).get(kind) if job else None
        return (path.read_bytes(), path.name) if path else None

    # ---- Claude-facing -------------------------------------------------------------------------------------
    def open_jobs(self, job_ids: list[str]) -> dict:
        """Queue jobs and open the first one in the default browser."""
        with self.lock:
            self.queue = list(job_ids)
        url = self.next_url()
        if url:
            self._open(url)
        return {"opened": url, "queued": len(self.queue)}

    def add_jobs(self, job_ids: list[str], front: bool = False) -> dict:
        """Add jobs to the running queue (no new window): at the end, or next in line with front=True.
        Opens the first one only if nothing is open yet."""
        new = list(dict.fromkeys(job_ids))
        with self.lock:
            rest = [j for j in self.queue if j not in new]
            self.queue = new + rest if front else rest + [j for j in new if j not in rest]
            idle = not self.pages
        if idle:
            return self.open_jobs(list(self.queue))
        return {"queued": len(self.queue), "opened": None}

    def current(self) -> dict | None:
        """The form the queue is on (the job ApplyBot opened last), else the one that reported most recently.
        Old tabs you kept open for later never take over from the queue."""
        with self.lock:
            if not self.pages:
                return None
            on_queue = [p for p in self.pages.values() if self.expected and p.get("job") == self.expected]
            return max(on_queue or self.pages.values(), key=lambda p: p.get("ts", 0))

    def set_fields(self, values: dict[str, str], confirmed_by_user: bool = False, tab: str | None = None) -> dict:
        """Queue live edits by field label (or key). Sensitive fields need confirmed_by_user."""
        with self.lock:
            page = self.pages.get(tab) if tab else self.current()
            if not page:
                return {"error": "no live form is open - open a job with the extension running first"}
            by_label = {(f.get("label") or "").strip().lower(): f for f in page["fields"]}
            by_key = {f["key"]: f for f in page["fields"]}
            queued, refused, unknown = [], [], []
            for name, value in values.items():
                f = by_key.get(name) or by_label.get(name.strip().lower())
                if not f:
                    unknown.append(name)
                elif f.get("kind") in ("password", "file"):
                    refused.append(f"{name}: {f['kind']} fields are yours to fill")
                elif is_sensitive(page["categories"].get(f["key"])) and not confirmed_by_user:
                    refused.append(f"{name}: legal / EEO / consent answer - ask the user, then pass confirmed_by_user")
                else:
                    self.commands.setdefault(page["tab"], []).append({"key": f["key"], "value": str(value)})
                    queued.append(name)
        return {"queued": queued, "refused": refused, "unknown": unknown}

    # ---- dashboard -----------------------------------------------------------------------------------------
    def feed(self) -> dict:
        cfg, _, db = self._context()
        page = self.current()
        with self.lock:
            queue = list(self.queue)
            log = list(self.log[-60:])
            auto = self.auto_submit if self.auto_submit is not None else bool((cfg.get("live") or {}).get("auto_submit"))
        jobs = {}
        for jid in queue[:25] + ([page["job"]] if page and page.get("job") else []):
            j = db.get_job(jid)
            if j:
                jobs[jid] = {"company": j["company"], "title": j["title"], "location": j.get("location") or ""}
        today = time.strftime("%Y-%m-%d")
        applied_today = db.conn.execute("SELECT COUNT(*) FROM applications WHERE status='applied' AND created_at LIKE ?",
                                        (today + "%",)).fetchone()[0]
        applied_total = db.conn.execute("SELECT COUNT(*) FROM jobs WHERE status='applied'").fetchone()[0]
        current = None
        if page:
            need = set(page["unresolved"])
            current = {"url": page["url"], "job": jobs.get(page.get("job")), "fields": [
                {"label": f.get("label") or "(unlabelled)", "kind": f.get("kind"),
                 "value": "" if f.get("kind") == "password" else str(f.get("value") or "")[:160],
                 "needs": f["key"] in need, "by_bot": f["key"] in page.get("filled", {})} for f in page["fields"]
                if f.get("kind") != "password"]}
        return {"connected": time.time() - self.last_seen < 20, "auto_submit": auto, "current": current,
                "queue": [{"id": j, **jobs.get(j, {"company": "?", "title": j})} for j in queue[:25]],
                "queued": len(queue), "log": log, "applied_today": applied_today, "applied_total": applied_total,
                "needs_you": self.needs_you()}

    # ---- jobs waiting on you -------------------------------------------------------------------------------
    def _needs_path(self, cfg) -> Path:
        return cfg.path("apply", "output_dir") / "needs_you.json"

    def needs_you(self) -> list[dict]:
        """Jobs ApplyBot couldn't finish alone (an essay to upload, a question only you can answer), newest first."""
        cfg, _, db = self._context()
        try:
            items = json.loads(self._needs_path(cfg).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            items = []
        out = []
        for it in items:
            job = db.get_job(it["id"])
            if job and job.get("status") != "applied":
                out.append({**it, "company": job["company"], "title": job["title"],
                            "url": form_url(job.get("apply_url") or job.get("url"))})
        return out

    def add_needs_you(self, job_id: str, reason: str) -> list[dict]:
        cfg, _, _ = self._context()
        path = self._needs_path(cfg)
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            items = []
        items = [i for i in items if i["id"] != job_id]
        items.insert(0, {"id": job_id, "reason": reason, "when": time.strftime("%Y-%m-%d %H:%M")})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, indent=1), encoding="utf-8")
        return self.needs_you()

    def control(self, tab: str, data: dict) -> dict:
        action = data.get("action")
        if action in ("pause", "resume"):
            self.auto_submit = action == "resume"
            self._note("auto-submit " + ("on" if self.auto_submit else "paused"))
            return {"auto_submit": self.auto_submit}
        if action == "focus":  # bring the tab ApplyBot is working in to the front
            page = self.current()
            if not page:
                return {"ok": False}
            with self.lock:
                self.commands.setdefault(page["tab"], []).append({"focus": True})
            return {"ok": True}
        if action == "reload_extension":
            self.ext_reload = True
            self._note("asked the extension to reload")
            return {"reload": True}
        if action == "skip":
            page = self.current()
            if page and page.get("job"):  # skipped = it needs you; keep it on your list
                need = [f.get("label") for f in page["fields"] if f["key"] in set(page["unresolved"])]
                self.add_needs_you(page["job"], data.get("reason") or ("still needs: " + "; ".join(need[:4]) if need
                                                                     else "skipped - finish it by hand"))
            url = self.next_url()
            if page and url:
                with self.lock:
                    self.commands.setdefault(page["tab"], []).append({"goto": url})
                self._note("skipped to the next job")
            return {"next": url}
        return {"error": "unknown action"}

    # ---- server --------------------------------------------------------------------------------------------
    def start(self, port: int = DEFAULT_PORT) -> int:
        if self.server:
            return self.port
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # stdout is the MCP channel; stay quiet
                pass

            def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj, code: int = 200):
                self._send(code, json.dumps(obj).encode())

            def _allowed(self, write: bool) -> bool:
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("127.0.0.1", "localhost"):
                    return False  # DNS-rebinding guard
                origin = self.headers.get("Origin")
                if origin and origin != "null" and not _ALLOWED_ORIGIN.match(origin):
                    return False  # a web page, not the extension
                return not write or self.headers.get("X-ApplyBot") == "1"

            def do_GET(self):
                u = urlparse(self.path)
                if not self._allowed(False):
                    return self._json({"error": "forbidden"}, 403)
                q = parse_qs(u.query)
                if u.path in ("/live", "/live/"):
                    return self._send(200, DASHBOARD.read_bytes(), "text/html; charset=utf-8",
                                      {"Cache-Control": "no-store", "X-Frame-Options": "DENY"})
                if u.path == "/live/feed":
                    return self._json(bridge.feed())
                if u.path == "/live/ping":
                    reload = False
                    if q.get("ext"):  # the extension's background page checking in
                        with bridge.lock:
                            reload, bridge.ext_reload = bridge.ext_reload, False
                    return self._json({"ok": True, "app": "applybot-live", "queued": len(bridge.queue), "reload": reload})
                if u.path == "/live/commands":
                    return self._json(bridge.take_commands(q.get("tab", ["0"])[0]))
                m = re.fullmatch(r"/live/file/([0-9a-f]+)/(\w+)", u.path)
                if m:
                    got = bridge.file_bytes(m.group(1), m.group(2))
                    if not got:
                        return self._json({"error": "no document"}, 404)
                    return self._send(200, got[0], "application/pdf", {"X-Filename": got[1]})
                return self._json({"error": "not found"}, 404)

            def do_POST(self):
                u = urlparse(self.path)
                if not self._allowed(True):
                    return self._json({"error": "forbidden"}, 403)
                try:
                    data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                except ValueError:
                    return self._json({"error": "bad json"}, 400)
                tab = str(data.get("tab", "0"))
                fn = {"/live/page": bridge.page, "/live/state": bridge.state, "/live/submitted": bridge.submitted,
                      "/live/confirmed": bridge.confirmed, "/live/control": bridge.control}.get(u.path)
                if not fn:
                    return self._json({"error": "not found"}, 404)
                try:
                    return self._json(fn(tab, data))
                except Exception as e:  # report instead of dropping the connection
                    bridge._note(f"error in {u.path}: {e}")
                    return self._json({"error": str(e)}, 500)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True, name="applybot-live").start()
        return self.port

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
