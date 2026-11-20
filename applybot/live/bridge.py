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
_ALLOWED_ORIGIN = re.compile(r"^(moz|chrome)-extension://")


def url_tokens(url: str) -> list[str]:
    """Stable id-looking pieces of a job URL (greenhouse job number, lever/ashby uuid, workable code)."""
    return _ID_RE.findall(url or "")


def is_sensitive(category: str | None) -> bool:
    return bool(category) and (category == "consent" or category.startswith(SENSITIVE_PREFIXES))


class LiveBridge:
    """State shared by the HTTP handler (the extension) and the MCP tools (Claude)."""

    def __init__(self, context: Callable[[], tuple], opener: Callable[[str], object] = webbrowser.open):
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
        return out

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
        return {"job": job and {"id": job["id"], "company": job["company"], "title": job["title"]},
                "fill": fill, "unresolved": unresolved}

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
        if not job:
            return self.next_url()
        with self.lock:
            self.expected = job["id"]
        return job.get("apply_url") or job.get("url")

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

    def current(self) -> dict | None:
        """The form that reported most recently."""
        with self.lock:
            return max(self.pages.values(), key=lambda p: p.get("ts", 0)) if self.pages else None

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
                if u.path == "/live/ping":
                    return self._json({"ok": True, "app": "applybot-live", "queued": len(bridge.queue)})
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
                      "/live/confirmed": bridge.confirmed}.get(u.path)
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
