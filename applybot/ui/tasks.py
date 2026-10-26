"""Background task runner for the UI: runs one long operation at a time, captures its log, and lets the
operation ask the user questions (answered from the UI) while it runs."""
from __future__ import annotations

import html
import sys
import threading
import time
import traceback
import uuid
from typing import Any, Callable

from rich.errors import MarkupError
from rich.markup import escape
from rich.text import Text

_COLORS = {"red", "green", "yellow", "blue", "cyan", "magenta", "white"}


class Cancelled(BaseException):
    """Raised inside a task when the user presses Stop. BaseException so `except Exception` won't swallow it."""


class Busy(RuntimeError):
    pass


def markup_to_html(line: str) -> str:
    """Convert Rich console markup ([bold], [yellow]...) to escaped HTML spans."""
    try:
        text = Text.from_markup(line)
    except (MarkupError, ValueError):
        return html.escape(line)
    plain = text.plain
    if not text.spans:
        return html.escape(plain)
    cuts = sorted({0, len(plain), *(s.start for s in text.spans), *(s.end for s in text.spans)})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        if a >= b:
            continue
        classes = []
        for s in text.spans:
            if s.start <= a and s.end >= b:
                for word in str(s.style).split():
                    if word in ("bold", "italic", "dim"):
                        classes.append(word)
                    elif word in _COLORS:
                        classes.append("c-" + word)
        seg = html.escape(plain[a:b])
        out.append(f'<span class="{" ".join(classes)}">{seg}</span>' if classes else seg)
    return "".join(out)


class Task:
    MAX_LINES = 5000

    def __init__(self, name: str, kind: str):
        self.id = uuid.uuid4().hex[:10]
        self.name = name
        self.kind = kind
        self.status = "running"
        self.started = time.time()
        self.ended: float | None = None
        self.error: str | None = None
        self.result: Any = None
        self.lines: list[dict] = []
        self.offset = 0  # number of lines dropped from the front
        self.prompt: dict | None = None
        self.stop_event = threading.Event()
        self._answer: Any = None
        self._answer_event = threading.Event()
        self._lock = threading.Lock()
        self.on_prompt: Callable[[], None] | None = None

    # ------------------------------------------------------------------ logging
    def log(self, msg: Any = "") -> None:
        if self.stop_event.is_set():
            raise Cancelled()
        now = time.time()
        with self._lock:
            for line in str(msg).split("\n"):
                self.lines.append({"t": now, "html": markup_to_html(line)})
            if len(self.lines) > self.MAX_LINES:
                drop = len(self.lines) - self.MAX_LINES
                del self.lines[:drop]
                self.offset += drop

    def lines_since(self, n: int) -> tuple[int, list[dict]]:
        with self._lock:
            start = max(0, n - self.offset)
            return self.offset + len(self.lines), self.lines[start:]

    # ------------------------------------------------------------------ prompts
    def ask(self, payload: dict) -> Any:
        """Block the task until the user answers in the UI. Raises Cancelled if the task is stopped."""
        self._answer_event.clear()
        self._answer = None
        self.prompt = {"id": uuid.uuid4().hex[:10], "created": time.time(), **payload}
        if self.on_prompt:
            try:
                self.on_prompt()
            except Exception:
                pass
        try:
            while not self._answer_event.wait(0.4):
                if self.stop_event.is_set():
                    raise Cancelled()
            return self._answer
        finally:
            self.prompt = None

    def answer(self, prompt_id: str, value: Any) -> bool:
        if not self.prompt or self.prompt.get("id") != prompt_id:
            return False
        self._answer = value
        self._answer_event.set()
        return True

    def stop(self) -> None:
        self.stop_event.set()

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "status": self.status,
                "started": self.started, "ended": self.ended, "error": self.error, "prompt": self.prompt,
                "stopping": self.stop_event.is_set() and self.status == "running"}


class TaskManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.current: Task | None = None
        self.on_prompt: Callable[[], None] | None = None
        self.on_done: Callable[[Task], None] | None = None

    @property
    def busy(self) -> bool:
        return self.current is not None and self.current.status == "running"

    def start(self, name: str, kind: str, fn: Callable[[Task], Any]) -> Task:
        with self._lock:
            if self.busy:
                raise Busy(f"'{self.current.name}' is still running")
            task = Task(name, kind)
            task.on_prompt = self.on_prompt
            self.current = task
        threading.Thread(target=self._run, args=(task, fn), daemon=True, name=f"task-{kind}").start()
        return task

    def _run(self, task: Task, fn: Callable[[Task], Any]) -> None:
        try:
            task.result = fn(task)
            task.status = "done"
        except Cancelled:
            task.status = "cancelled"
            task.stop_event.clear()
            task.log("[yellow]Stopped.[/yellow]")
        except Exception as e:  # surface any failure in the UI instead of dying silently
            task.status = "failed"
            task.error = f"{type(e).__name__}: {e}"
            tb = traceback.format_exc()
            print(tb, file=sys.stderr)
            task.stop_event.clear()
            task.log(f"[red]Error: {escape(task.error)}[/red]")
        finally:
            task.ended = time.time()
            task.prompt = None
            if self.on_done:
                try:
                    self.on_done(task)
                except Exception:
                    pass
