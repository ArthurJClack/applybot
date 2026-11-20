"""SQLite-backed tracker for discovered jobs and submitted applications."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from applybot.models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    fingerprint TEXT,
    source TEXT, external_id TEXT, company TEXT, title TEXT, url TEXT, apply_url TEXT,
    location TEXT, description TEXT, job_type TEXT, remote INTEGER, posted_at TEXT, extra TEXT,
    score REAL, score_reason TEXT,
    status TEXT DEFAULT 'new',
    created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_fp ON jobs(fingerprint);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT, url TEXT, status TEXT, mode TEXT,
    resume_path TEXT, cover_letter_path TEXT, answers TEXT, notes TEXT,
    created_at TEXT
);
"""

STATUSES = ("new", "matched", "rejected", "tailored", "applied", "interviewing", "offer", "rejected_by_company",
            "needs_review", "failed", "skipped")
SUBMITTED = ("applied", "interviewing", "offer", "rejected_by_company")  # statuses that mean "we sent an application"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(jobs)")}
        if "ats_key" not in cols:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN ats_key TEXT DEFAULT ''")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_ats ON jobs(ats_key)")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            from applybot.sources.ashby import company_name
            from applybot.sources import is_remote
            from applybot.sources.ats import dedupe_key
            seen: set[str] = set()
            rows = self.conn.execute("SELECT id, url, apply_url, source, company, status, location FROM jobs "
                                     "ORDER BY created_at, rowid").fetchall()
            for r in rows:
                key = dedupe_key(r["apply_url"], r["url"])
                updates = {"ats_key": key}
                if r["source"] in ("ashby", "lever") and r["company"] and r["company"] == r["company"].lower():
                    updates["company"] = company_name(r["company"])
                if r["source"] == "ashby":  # old rows trusted Ashby's unreliable isRemote flag
                    updates["remote"] = int(is_remote(r["location"] or ""))
                if key and key in seen and r["status"] == "new":
                    updates["status"] = "skipped"
                    updates["score_reason"] = "duplicate of a posting from another source"
                if key:
                    seen.add(key)
                sets = ", ".join(f"{k}=?" for k in updates)
                self.conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*updates.values(), r["id"]))
            self.conn.execute("PRAGMA user_version = 1")
            self.conn.commit()

    def close(self):
        self.conn.close()

    def upsert_job(self, job: Job) -> bool:
        """Insert a job if neither its id nor its fingerprint is known. Returns True if inserted."""
        from applybot.sources.ats import dedupe_key
        d = job.to_dict()
        key = dedupe_key(d["apply_url"], d["url"])
        # same posting seen via another source (e.g. Simplify + the company's Greenhouse board) counts as known
        cur = self.conn.execute("SELECT 1 FROM jobs WHERE id=? OR fingerprint=? OR (?<>'' AND ats_key=?)",
                                (d["id"], d["fingerprint"], key, key))
        if cur.fetchone():
            # refresh description if we now have a better one
            if d["description"]:
                self.conn.execute(
                    "UPDATE jobs SET description=?, updated_at=? WHERE id=? AND (description IS NULL OR description='')",
                    (d["description"], now(), d["id"]))
                self.conn.commit()
            return False
        self.conn.execute(
            """INSERT INTO jobs (id, fingerprint, source, external_id, company, title, url, apply_url, location,
               description, job_type, remote, posted_at, extra, ats_key, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'new', ?, ?)""",
            (d["id"], d["fingerprint"], d["source"], d["external_id"], d["company"], d["title"], d["url"],
             d["apply_url"] or d["url"], d["location"], d["description"], d["job_type"], int(d["remote"]),
             d["posted_at"], json.dumps(d["extra"]), key, now(), now()))
        self.conn.commit()
        return True

    def get_job(self, job_id: str) -> dict | None:
        """Exact id, or a unique id prefix (an ambiguous prefix returns None rather than a random job)."""
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row:
            return self._row(row)
        if not job_id:
            return None
        esc = job_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.conn.execute("SELECT * FROM jobs WHERE id LIKE ? ESCAPE '\\' LIMIT 2", (esc + "%",)).fetchall()
        return self._row(rows[0]) if len(rows) == 1 else None

    def list_jobs(self, status: str | None = None, min_score: float | None = None, limit: int = 50,
                  unscored: bool = False, order: str = "score") -> list[dict]:
        q, args = "SELECT * FROM jobs WHERE 1=1", []
        if status:
            q += " AND status=?"
            args.append(status)
        if min_score is not None:
            q += " AND score >= ?"
            args.append(min_score)
        if unscored:
            q += " AND score IS NULL"
        q += " ORDER BY score DESC, posted_at DESC" if order == "score" else " ORDER BY posted_at DESC"
        q += " LIMIT ?"
        args.append(limit)
        return [self._row(r) for r in self.conn.execute(q, args).fetchall()]

    def update_job(self, job_id: str, **fields):
        if not fields:
            return
        fields["updated_at"] = now()
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))
        self.conn.commit()

    def log_application(self, job_id: str | None, url: str, status: str, mode: str, resume_path: str = "",
                        cover_letter_path: str = "", answers: dict | None = None, notes: str = ""):
        self.conn.execute(
            """INSERT INTO applications (job_id, url, status, mode, resume_path, cover_letter_path, answers, notes,
               created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (job_id, url, status, mode, resume_path, cover_letter_path, json.dumps(answers or {}), notes, now()))
        self.conn.commit()

    def company_app_counts(self) -> dict[str, int]:
        """How many applications have gone to each company (lowercased), in any post-submit status."""
        marks = ",".join("?" * len(SUBMITTED))
        return {r[0]: r[1] for r in self.conn.execute(
            f"SELECT LOWER(company), COUNT(*) FROM jobs WHERE status IN ({marks}) GROUP BY LOWER(company)",
            SUBMITTED)}

    def export_csv(self, out_dir: str | Path) -> list[Path]:
        """Write jobs.csv and applications.csv (for spreadsheets / your own tracking)."""
        import csv
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for name, query in (("jobs", "SELECT id, status, score, company, title, location, job_type, remote, source, "
                                     "posted_at, url, apply_url, score_reason, created_at, updated_at FROM jobs "
                                     "ORDER BY score DESC, posted_at DESC"),
                            ("applications", "SELECT created_at, job_id, status, mode, url, resume_path, "
                                             "cover_letter_path, notes FROM applications ORDER BY id DESC")):
            rows = self.conn.execute(query).fetchall()
            path = out / f"{name}.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel opens it as UTF-8
                w = csv.writer(f)
                w.writerow(rows[0].keys() if rows else [])
                w.writerows(rows)
            paths.append(path)
        return paths

    def applied_today(self) -> int:
        start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status='applied' AND created_at >= ?",
            (start.astimezone(timezone.utc).isoformat(timespec="seconds"),)).fetchone()[0]

    def status_counts(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self.conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")}

    def applications(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM applications ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["extra"] = json.loads(d.get("extra") or "{}")
        except json.JSONDecodeError:
            d["extra"] = {}
        d["remote"] = bool(d.get("remote"))
        return d
