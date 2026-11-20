"""Read emailed verification codes (Greenhouse "security code", etc.) from your own inbox and type them in.

Read-only IMAP: the inbox is opened with readonly=True, nothing is marked read, moved or deleted, and only
messages that arrived after the application was submitted are looked at.

Setup (Gmail, one time):
  1. Turn on 2-Step Verification, then create an app password at https://myaccount.google.com/apppasswords
  2. Put it in .env (never in config.yaml):
         APPLYBOT_MAIL_USER=you@gmail.com
         APPLYBOT_MAIL_APP_PASSWORD=abcd efgh ijkl mnop
  3. config.yaml:
         mail:
           enabled: true
  4. Test it: `python main.py mail-code`
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import re
import time
from datetime import datetime, timedelta, timezone
from email.message import Message
from typing import Callable

from applybot.sources import html_to_text

SENDER_RE = re.compile(r"greenhouse|lever\.co|ashby|workday|icims|smartrecruiters|workable|no-?reply", re.I)
SUBJECT_RE = re.compile(r"security code|verification code|verify|confirm your|one[- ]time|passcode", re.I)
PROMPT_RE = re.compile(r"security code|verification code|code (?:we|was) (?:sent|emailed)|enter the code", re.I)
FIELD_RE = re.compile(r"security.?(?:code|input)|verification.?code|one.?time.?(?:code|pass)|passcode|otp", re.I)

_AFTER_CODE = re.compile(r"code(?:\s+is)?\s*[:\-]?\s*([A-Za-z0-9]{4,10})\b")
_OWN_LINE = re.compile(r"^\s*([A-Za-z0-9]{6,10})\s*$", re.M)


def _looks_like_code(tok: str) -> bool:
    """A code has a digit, or mixes upper and lower case mid-word - ordinary words do neither."""
    if any(c.isdigit() for c in tok):
        return True
    return tok != tok.lower() and tok != tok.upper() and tok != tok.capitalize()


def extract_code(text: str) -> str | None:
    """Pull the verification code out of an email's text, or None if there isn't one."""
    text = text or ""
    for rx in (_AFTER_CODE, _OWN_LINE):
        for m in rx.finditer(text):
            if _looks_like_code(m.group(1)):
                return m.group(1)
    return None


def _body(msg: Message) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    plain, html = [], []
    for p in parts:
        ctype = p.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        raw = p.get_payload(decode=True) or b""
        text = raw.decode(p.get_content_charset() or "utf-8", errors="replace")
        (plain if ctype == "text/plain" else html).append(text)
    return "\n".join(plain) if plain else html_to_text("\n".join(html))


def code_from_message(msg: Message, since: datetime) -> str | None:
    """The code in `msg` if it is a verification email that arrived at or after `since`."""
    try:
        sent = email.utils.parsedate_to_datetime(msg.get("Date", ""))
    except (TypeError, ValueError):
        return None
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    if sent < since:
        return None
    if not (SENDER_RE.search(msg.get("From", "")) or SUBJECT_RE.search(msg.get("Subject", ""))):
        return None
    return extract_code(msg.get("Subject", "") + "\n" + _body(msg))


class MailCodes:
    def __init__(self, cfg: dict, log: Callable[[str], None] = print):
        m = cfg.get("mail") or {}
        self.enabled = bool(m.get("enabled"))
        self.host = m.get("imap_host") or "imap.gmail.com"
        self.user = (m.get("user") or "").strip()
        self.password = (m.get("app_password") or "").replace(" ", "")
        self.wait_seconds = int(m.get("wait_seconds", 90))
        self.log = log

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.user and self.password)

    def _recent(self, since: datetime, limit: int = 15) -> list[Message]:
        box = imaplib.IMAP4_SSL(self.host)
        try:
            box.login(self.user, self.password)
            box.select("INBOX", readonly=True)
            day = (since - timedelta(days=1)).strftime("%d-%b-%Y")
            _, data = box.search(None, f"(SINCE {day})")
            ids = (data[0] or b"").split()[-limit:]
            out = []
            for i in reversed(ids):
                _, parts = box.fetch(i, "(BODY.PEEK[])")
                if parts and parts[0]:
                    out.append(email.message_from_bytes(parts[0][1]))
            return out
        finally:
            try:
                box.logout()
            except Exception:
                pass

    def latest_code(self, since: datetime) -> str | None:
        for msg in self._recent(since):
            code = code_from_message(msg, since)
            if code:
                return code
        return None

    def wait_for_code(self, since: datetime, timeout: int | None = None, poll: float = 5.0) -> str | None:
        deadline = time.monotonic() + (self.wait_seconds if timeout is None else timeout)
        while True:
            code = self.latest_code(since)
            if code or time.monotonic() >= deadline:
                return code
            time.sleep(poll)


_FIND_FIELDS = """(pattern) => {
  const rx = new RegExp(pattern, 'i');
  const ins = [...document.querySelectorAll('input')].filter(e => {
    if (e.type === 'hidden' || e.disabled || !e.offsetParent) return false;
    const label = e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]');
    return rx.test([e.id, e.name, e.placeholder, e.getAttribute('aria-label'), e.autocomplete,
                    label ? label.innerText : ''].join(' '));
  });
  ins.forEach((e, i) => e.setAttribute('data-applybot-code', String(i)));
  return ins.map(e => e.maxLength);
}"""


def fill_email_code(page, cfg: dict, since: datetime, log: Callable[[str], None] = print) -> bool:
    """If `page` is asking for an emailed code, fetch it from the inbox and type it in. True if it did."""
    mail = MailCodes(cfg, log)
    if not mail.ready:
        return False
    for frame in page.frames:
        try:
            lengths = frame.evaluate(_FIND_FIELDS, FIELD_RE.pattern)
        except Exception:
            continue
        if not lengths:
            continue
        log("the form asked for an emailed code - checking your inbox...")
        try:
            code = mail.wait_for_code(since)
        except (imaplib.IMAP4.error, OSError) as e:
            log(f"[yellow]couldn't read the inbox: {e}[/yellow]")
            return False
        if not code:
            log("[yellow]no code email arrived in time[/yellow]")
            return False
        boxes = frame.locator("[data-applybot-code]")
        if len(lengths) > 1 and all(n == 1 for n in lengths):  # one box per character
            for i, ch in enumerate(code[: len(lengths)]):
                boxes.nth(i).fill(ch)
        else:
            boxes.first.fill(code)
        log("entered the emailed code")
        return True
    return False


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
