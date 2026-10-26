from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


@dataclass
class Job:
    source: str
    external_id: str
    company: str
    title: str
    url: str
    apply_url: str = ""
    location: str = ""
    description: str = ""
    job_type: str = ""  # internship | full-time | part-time | contract | ""
    remote: bool = False
    posted_at: str = ""  # ISO-8601
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.source}:{self.external_id}".encode()).hexdigest()[:10]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha1(f"{norm(self.company)}|{norm(self.title)}|{norm(self.location)}".encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        d["fingerprint"] = self.fingerprint
        return d
