"""MCP tools that let Claude see and edit the application form that is open in your own browser."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from applybot.live.bridge import DEFAULT_PORT, LiveBridge

EXTENSION_DIR = Path(__file__).parent / "extension"
_bridge: LiveBridge | None = None


def bridge(context: Callable[[], tuple]) -> LiveBridge:
    global _bridge
    if _bridge is None:
        _bridge = LiveBridge(context)
    return _bridge


def register(tool: Callable, context: Callable[[], tuple]) -> None:
    """Add the live_* tools. `tool` is the MCP tool decorator, `context` returns (cfg, profile, db)."""

    def _port(cfg) -> int:
        return int((cfg.get("live") or {}).get("port", DEFAULT_PORT))

    def _up() -> LiveBridge:
        b = bridge(context)
        if not b.server:
            b.start(_port(context()[0]))
        return b

    @tool
    def live_start() -> dict:
        """Start live apply: forms are filled inside the user's OWN browser (their saved logins and sessions keep
        working) through the ApplyBot Live extension. Returns the extension folder and whether the extension has
        connected yet. Safe to call again."""
        b = _up()
        import time
        return {"listening": f"127.0.0.1:{b.port}", "extension_folder": str(EXTENSION_DIR),
                "extension_connected": time.time() - b.last_seen < 30,
                "install": "Firefox: open about:debugging#/runtime/this-firefox -> Load Temporary Add-on -> pick "
                           "manifest.json in extension_folder. It stays until Firefox restarts."}

    @tool
    def live_open(job_ids: list[str]) -> dict:
        """Queue jobs for live apply and open the first one in the user's default browser. The extension fills each
        form; the user reviews, signs in if needed, and clicks submit. The confirmation page marks the job applied,
        saves any answers the user typed by hand, and opens the next job in the same tab."""
        return _up().open_jobs(job_ids)

    @tool
    def live_status() -> dict:
        """What is on the live form right now: every field with its current value, which required ones are still
        empty, the matched job, and recent activity. Use it to see what the user is stuck on."""
        b = _up()
        page = b.current()
        if not page:
            return {"form": None, "queued": len(b.queue), "log": b.log[-10:],
                    "note": "no form reported yet - is the extension loaded and a job page open?"}
        need = set(page["unresolved"])
        return {"url": page["url"], "job": page["job"], "queued": len(b.queue), "log": b.log[-10:],
                "fields": [{"label": f.get("label"), "kind": f.get("kind"), "value": f.get("value"),
                            "options": (f.get("options") or [])[:25], "needs_answer": f["key"] in need,
                            "category": page["categories"].get(f["key"])} for f in page["fields"]]}

    @tool
    def live_fill(values: dict[str, str], confirmed_by_user: bool = False) -> dict:
        """Type answers into the live form, keyed by field label (as shown by live_status). The page updates within
        a couple of seconds. Password and file fields are refused. Legal, EEO, work-authorization and consent
        answers are refused unless the user gave that exact answer and you pass confirmed_by_user=True."""
        return _up().set_fields(values, confirmed_by_user)
