import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from applybot.profile import parse_structured  # noqa: E402

TEMPLATE_PROFILE = (ROOT / "applybot" / "templates" / "profile.example.txt").read_text(encoding="utf-8")


class FakeLLM:
    """Deterministic stand-in for the AI wrapper. `handler(prompt) -> dict|str`."""

    def __init__(self, handler=None):
        self.available = True
        self.prompts: list[str] = []
        self.handler = handler or (lambda prompt: {})

    def complete(self, prompt, system=None, json_mode=False, max_tokens=None):
        self.prompts.append(prompt)
        out = self.handler(prompt)
        return out if isinstance(out, str) else json.dumps(out)

    def complete_json(self, prompt, system=None, max_tokens=None):
        self.prompts.append(prompt)
        out = self.handler(prompt)
        return json.loads(out) if isinstance(out, str) else out


@pytest.fixture
def profile():
    p = parse_structured(TEMPLATE_PROFILE)
    p["raw"] = TEMPLATE_PROFILE
    return p


@pytest.fixture
def job():
    return {
        "id": "abc123", "company": "Widgets Inc", "title": "Backend Software Engineer Intern",
        "location": "Remote", "remote": True, "job_type": "internship", "extra": {},
        "description": "We need Python, FastAPI, PostgreSQL and Redis experience. Docker and AWS a plus. "
                       "You will build APIs and data pipelines.",
        "url": "https://example.com/job", "apply_url": "https://example.com/job",
    }
