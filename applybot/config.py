"""Configuration loading with sane defaults and ${ENV_VAR} expansion."""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "ai": {
        # openai | anthropic | gemini | ollama | openai_compatible | command | none
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "${OPENAI_API_KEY}",
        "base_url": None,
        "temperature": None,
        "max_tokens": 4000,
        "timeout": 120,
        # Only used by provider=command: a shell command that reads the prompt on stdin
        "command": None,
    },
    "profile": {
        "path": "profile.txt",
        "answers_path": "answers.yaml",
        "cache_path": ".cache/profile.json",
        "parser": "auto",  # auto | structured | ai
    },
    "search": {
        "keywords": ["software engineer", "software developer", "intern"],
        "exclude_keywords": ["senior", "sr.", "staff", "principal", "director", "manager", "lead"],
        "locations": [],  # empty = anywhere
        "remote_ok": True,
        "max_age_days": 45,
        "max_per_source": 500,
        "sources": {
            "simplify": {
                "enabled": True,
                "repos": ["SimplifyJobs/Summer2027-Internships", "SimplifyJobs/New-Grad-Positions"],
            },
            "greenhouse": {"enabled": True, "companies": ["stripe", "airbnb", "databricks", "figma"]},
            "lever": {"enabled": True, "companies": ["palantir", "plaid"]},
            "ashby": {"enabled": True, "companies": ["ramp", "notion", "openai"]},
            "remotive": {"enabled": True},
            "remoteok": {"enabled": False},
            "arbeitnow": {"enabled": False},
            "jobspy": {
                "enabled": False,
                "sites": ["indeed", "linkedin", "glassdoor", "zip_recruiter"],
                "results_wanted": 50,
                "location": "United States",
                "hours_old": 168,
            },
        },
    },
    "matching": {"use_ai": True, "min_score": 60},
    "apply": {
        "mode": "review",  # dry_run | review | auto
        "headless": False,
        "max_per_run": 10,
        "max_per_day": 25,
        "delay_seconds": [15, 45],
        "max_steps": 8,
        "cover_letter": True,
        "resume_formats": ["pdf", "docx"],
        "browser_profile_dir": ".browser_profile",
        "output_dir": "output",
    },
    "database": "applybot.db",
}

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(2) or "")
        return _ENV_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


_DOTENV_KEYS: set[str] = set()


def load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Never overrides real environment variables, but values that
    came from a previous .env load are refreshed so edits take effect in long-running sessions."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key in os.environ and key not in _DOTENV_KEYS:
            continue
        os.environ[key] = val
        _DOTENV_KEYS.add(key)


class Config(dict):
    """Plain dict plus `base_dir`, used to resolve relative paths."""

    base_dir: Path = Path.cwd()

    def path(self, *keys: str) -> Path:
        node: Any = self
        for k in keys:
            node = node[k]
        p = Path(node)
        return p if p.is_absolute() else self.base_dir / p


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    base_dir = path.resolve().parent
    load_dotenv(base_dir / ".env")
    user: dict = {}
    if path.exists():
        user = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = Config(_expand(deep_merge(DEFAULTS, user)))
    cfg.base_dir = base_dir
    return cfg

TEMPLATES = Path(__file__).parent / "templates"
WORKSPACE_FILES = (("config.example.yaml", "config.yaml"), ("profile.example.txt", "profile.txt"),
                   ("answers.example.yaml", "answers.yaml"), ("env.example", ".env"))


def init_workspace(base: Path) -> list[str]:
    """Copy any missing starter files (config, profile, answers, .env) into `base`. Returns names created."""
    import shutil
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    created = []
    for src, dst in WORKSPACE_FILES:
        target = base / dst
        if not target.exists():
            shutil.copy(TEMPLATES / src, target)
            created.append(dst)
    return created
