"""Starts the UI server and shows it in a standalone app window (Edge/Chrome `--app` mode, no browser chrome).

Lifecycle: the server stops shortly after the window is closed (unless a task is still running).
A second launch re-opens a window onto the already-running instance."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

APP_HOME = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ApplyBot"  # window profile, logs, instance info
INSTANCE_FILE = APP_HOME / "instance.json"
DEFAULT_PORT = 47815


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def documents_dir() -> Path:
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # CSIDL_PERSONAL
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


def default_data_dir() -> Path:
    if os.environ.get("APPLYBOT_HOME"):
        return Path(os.environ["APPLYBOT_HOME"])
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "config.yaml").exists():  # portable mode: data lives next to the .exe
            return exe_dir
        return documents_dir() / "ApplyBot"
    return Path.cwd()


def find_app_browser() -> str | None:
    candidates = []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates += [Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                           Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"]
    for c in candidates:
        if c.exists():
            return str(c)
    for name in ("msedge", "google-chrome", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def show_window(url: str) -> subprocess.Popen | None:
    exe = find_app_browser()
    if exe:
        profile = APP_HOME / "window"
        profile.mkdir(parents=True, exist_ok=True)
        try:
            return subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1440,920",
                                     "--no-first-run", "--no-default-browser-check", "--disable-sync",
                                     "--disable-features=Translate"])
        except OSError:
            pass
    webbrowser.open(url)
    return None


def focus_app_window() -> None:
    """Bring the ApplyBot window forward (or flash it in the taskbar) when a task needs the user."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.startswith("ApplyBot") or buf.value.startswith("(!) ApplyBot"):
                found.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)

    class FLASHWINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                    ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]

    for hwnd in found:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 3 | 12, 0, 0)  # FLASHW_ALL | FLASHW_TIMERNOFG
        user32.FlashWindowEx(ctypes.byref(info))


def existing_instance(data_dir: Path) -> str | None:
    try:
        info = json.loads(INSTANCE_FILE.read_text(encoding="utf-8"))
        if Path(info["data_dir"]).resolve() != data_dir.resolve():
            return None
        req = urllib.request.Request(info["url"] + "api/ping", headers={"X-ApplyBot": "1"})
        with urllib.request.urlopen(req, timeout=1.5) as r:
            if json.load(r).get("app") == "applybot":
                return info["url"]
    except Exception:
        return None
    return None


def run(config_path: Path, port: int = 0, open_window: bool = True) -> int:
    from applybot.ui.server import App, make_server

    config_path = Path(config_path).resolve()
    data_dir = config_path.parent
    APP_HOME.mkdir(parents=True, exist_ok=True)

    url = existing_instance(data_dir)
    if url:
        print(f"ApplyBot is already running at {url}")
        if open_window:
            show_window(url)
        return 0

    app = App(config_path)
    server = make_server(app, port or DEFAULT_PORT)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    INSTANCE_FILE.write_text(json.dumps({"url": url, "data_dir": str(data_dir), "pid": os.getpid()}),
                             encoding="utf-8")
    threading.Thread(target=server.serve_forever, daemon=True, name="ui-server").start()
    app.attention_hooks.append(focus_app_window)
    print(f"ApplyBot is running at {url}\nData folder: {data_dir}\nPress Ctrl+C to quit.")

    proc = show_window(url) if open_window else None
    proc_started = time.time()
    closed_at = 0.0
    try:
        while True:
            time.sleep(1.0)
            if not open_window:
                continue
            now = time.time()
            if proc is not None and proc.poll() is not None:
                if now - proc_started > 8:  # a quick exit means the browser handed the window to another process
                    closed_at = now
                proc = None
            said_bye = (closed_at or app.bye_at) and max(closed_at, app.bye_at) >= app.last_seen - 1
            gone = (said_bye and now - app.last_seen > 8) or now - app.last_seen > 300
            if not gone:
                continue
            task = app.tasks.current
            if not app.tasks.busy:
                break
            if task is not None and task.prompt:  # nobody is left to answer it
                task.stop()
    except KeyboardInterrupt:
        pass
    finally:
        task = app.tasks.current
        if task is not None and app.tasks.busy:
            task.stop()
        server.shutdown()
        try:
            INSTANCE_FILE.unlink()
        except OSError:
            pass
    return 0


def _prepare_frozen_runtime() -> None:
    log_path = APP_HOME / "applybot.log"
    APP_HOME.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:  # windowed .exe has no console
        stream = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives for the process
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    # The packaged app keeps Playwright's browser in the normal per-user cache, not inside the .exe.
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path(os.environ.get("LOCALAPPDATA") or Path.home())
                                                          / "ms-playwright"))


def _error_box(message: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "ApplyBot", 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the packaged desktop app (ApplyBot.exe)."""
    if is_frozen():
        _prepare_frozen_runtime()
    from applybot.cli import build_parser, main as cli_main
    raw = sys.argv[1:] if argv is None else argv
    commands = next(a.choices for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    if set(raw) & set(commands):  # "ApplyBot.exe refresh" etc. run the CLI instead of opening a window
        data = default_data_dir()
        if "--data" in raw:
            i = raw.index("--data")
            data = Path(raw[i + 1])
            raw = raw[:i] + raw[i + 2:]
        if "-c" not in raw and "--config" not in raw:
            raw = ["-c", str(data / "config.yaml"), *raw]
        return cli_main(raw)
    p = argparse.ArgumentParser(prog="ApplyBot")
    p.add_argument("--data", help="folder for your profile, settings, and application history")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-window", action="store_true")
    args, _ = p.parse_known_args(argv)
    data_dir = Path(args.data) if args.data else default_data_dir()
    try:
        return run(data_dir / "config.yaml", port=args.port, open_window=not args.no_window)
    except Exception as e:
        traceback.print_exc()
        _error_box(f"ApplyBot could not start:\n\n{type(e).__name__}: {e}\n\nLog: {APP_HOME / 'applybot.log'}")
        return 1
