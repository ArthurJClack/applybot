"""Browser automation that fills and submits arbitrary web application forms with Playwright.

Works on any site (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, custom forms, scholarship/college forms...)
by scanning the DOM for form controls, resolving each question via the AnswerBank/AI, filling, uploading files,
and walking multi-step forms. CAPTCHAs and logins are never bypassed - they are handed to you.
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from applybot.answers import (SENSITIVE_PREFIXES, AnswerBank, Field, Resolution, choose_option, classify,
                              resolve_fields)
from applybot.llm import LLM

SCAN_JS = "\n".join(ln for ln in (Path(__file__).with_name("scan_form.js")).read_text(encoding="utf-8").splitlines()
                    if not ln.lstrip().startswith("//"))

SUBMIT_RE = re.compile(r"^\s*(submit( your| my)?( application)?|send( application)?|complete( application)?"
                       r"|finish( application)?|submit & apply)\s*[\u2192>]?\s*$", re.I)
NEXT_RE = re.compile(r"^\s*(next|continue|save (and|&) continue|next step|proceed|review( application)?|"
                     r"continue to next step)\s*[\u2192>]?\s*$", re.I)
APPLY_RE = re.compile(r"^\s*(apply|apply now|apply for this (job|position|role)|apply to this (job|position)|"
                      r"i'?m interested|start application|easy apply)\s*$", re.I)
CONFIRM_RE = re.compile(r"thank(s| you) for (applying|your (application|interest|submission))|application (has been |was )?"
                        r"(received|submitted)|we('ve| have) received your|successfully submitted|submission (received|"
                        r"successful)|your application is (complete|in)", re.I)


@dataclass
class ApplyResult:
    status: str  # applied | dry_run | needs_review | failed | skipped
    notes: str = ""
    answers: dict = field(default_factory=dict)
    screenshot: str = ""
    final_url: str = ""


def _is_tty() -> bool:
    return bool(sys.stdin and sys.stdin.isatty())


_GH_JOB = re.compile(r"^https?://(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/([\w.-]+)/jobs/(\d+)", re.I)
_LEVER_JOB = re.compile(r"^(https?://jobs\.(?:eu\.)?lever\.co/[\w.-]+/[0-9a-f-]{36})/?(?:[?#].*)?$", re.I)
_ASHBY_JOB = re.compile(r"^(https?://jobs\.ashbyhq\.com/[^/?#]+/[0-9a-f-]{36})/?(?:[?#].*)?$", re.I)


def direct_form_url(url: str) -> str:
    """Point known ATS job pages straight at their application form.

    Greenhouse boards often redirect to a company's own careers site (with the form hidden behind a tab or
    iframe); the embed URL always serves the plain hosted form."""
    m = _GH_JOB.match(url)
    if m:
        host = "job-boards.eu.greenhouse.io" if ".eu." in url.lower() else "job-boards.greenhouse.io"
        return f"https://{host}/embed/job_app?for={m.group(1)}&token={m.group(2)}"
    m = _LEVER_JOB.match(url)
    if m:
        return m.group(1) + "/apply"
    m = _ASHBY_JOB.match(url)
    if m:
        return m.group(1) + "/application"
    # company careers pages that embed Greenhouse (e.g. stokespace.com/careers?gh_jid=123)
    from applybot.sources.ats import ats_key
    key = ats_key(url)
    if key and key[0] == "greenhouse" and key[1]:
        return f"https://job-boards.greenhouse.io/embed/job_app?for={key[1]}&token={key[2]}"
    return url


# Sites where every application needs a candidate account/sign-in, which the bot never creates.
ACCOUNT_SITES = ("myworkdayjobs.com", "myworkdaysite.com", "amazon.jobs", "careers.microsoft.com", "metacareers.com",
                 "successfactors", "avature.net", "icims.com", "taleo.net", "oraclecloud.com", "brassring.com")


def account_site(url: str) -> str:
    low = (url or "").lower()
    return next((s for s in ACCOUNT_SITES if s in low), "")


Choices = list[tuple[str, str]]  # (value returned, label shown)
PauseFn = Callable[[str, Choices, dict | None], str]


def install_browser(log: Callable[[str], None] = print) -> bool:
    """Download Playwright's Chromium (works from source and from the packaged .exe)."""
    import subprocess
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    exe, cli = compute_driver_executable()
    log("Installing the Chromium browser used for applications (one-time, ~150 MB)...")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run([exe, cli, "install", "chromium"], env=get_driver_env(), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", **kwargs)
    if proc.returncode != 0:
        log(f"[red]browser install failed:[/red] {(proc.stderr or proc.stdout)[-500:]}")
        return False
    log("[green]Browser installed.[/green]")
    return True


class Applicant:
    def __init__(self, cfg: dict, profile: dict, bank: AnswerBank, llm: LLM | None,
                 log: Callable[[str], None] = print, ask_human: Callable[[Field], str | None] | None = None,
                 pause: PauseFn | None = None):
        self.cfg = cfg
        self.acfg = cfg["apply"]
        self.profile = profile
        self.bank = bank
        self.llm = llm
        self.log = log
        self.ask_human = ask_human
        self.pause_fn = pause
        self._pw = None
        self._ctx = None

    @property
    def interactive(self) -> bool:
        """True when a human can act in the browser window (it must be visible)."""
        if self.acfg.get("headless"):
            return False
        return self.pause_fn is not None or _is_tty()

    # ------------------------------------------------------------------ browser lifecycle
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        user_dir = Path(self.acfg.get("browser_profile_dir", ".browser_profile"))
        if not user_dir.is_absolute():
            user_dir = Path(getattr(self.cfg, "base_dir", Path.cwd())) / user_dir

        def launch():
            return self._pw.chromium.launch_persistent_context(
                str(user_dir), headless=bool(self.acfg.get("headless")), viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"])

        try:
            self._ctx = launch()
        except Exception as e:
            if "Executable doesn't exist" not in str(e) or not install_browser(self.log):
                self._pw.stop()
                raise
            self._ctx = launch()
        self._ctx.set_default_timeout(15000)
        return self

    def __exit__(self, *exc):
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    # ------------------------------------------------------------------ helpers
    def _pause(self, message: str, choices: Choices | None = None, details: dict | None = None) -> str:
        """Hand control to the human. Returns the chosen value ('' if non-interactive)."""
        choices = choices or [("", "Continue")]
        if self.pause_fn is not None:
            return (self.pause_fn(message, choices, details) or "").strip().lower()
        if not _is_tty():
            return ""
        hint = " / ".join(f"{v or 'Enter'} = {label}" for v, label in choices)
        return input(f"\n>>> {message}\n    [{hint}] ").strip().lower()

    def _settle(self, page, ms: int = 1500):
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(ms)

    def _frames(self, page):
        return [f for f in page.frames if not f.is_detached()]

    def _scan(self, page) -> list[tuple[object, dict]]:
        found = []
        for frame in self._frames(page):
            try:
                for item in frame.evaluate(SCAN_JS):
                    found.append((frame, item))
            except Exception:
                continue  # cross-origin/detached frames
        return found

    def _find_button(self, page, pattern: re.Pattern):
        for frame in self._frames(page):
            for role in ("button", "link"):
                try:
                    loc = frame.get_by_role(role, name=pattern)
                    for i in range(min(loc.count(), 5)):
                        cand = loc.nth(i)
                        if cand.is_visible() and cand.is_enabled():
                            return cand
                except Exception:
                    continue
        return None

    def detect_captcha(self, page) -> bool:
        for frame in self._frames(page):
            url = frame.url or ""
            if any(s in url for s in ("recaptcha/api2/bframe", "hcaptcha.com/captcha", "challenges.cloudflare.com")):
                try:
                    el = frame.frame_element()
                    box = el.bounding_box()
                    if box and box["width"] > 50 and box["height"] > 50 and el.is_visible():
                        return True
                except Exception:
                    continue
        return False

    def detect_login(self, page) -> bool:
        try:
            return page.locator("input[type=password]:visible").count() > 0
        except Exception:
            return False

    def _errors(self, page) -> list[str]:
        js = """() => Array.from(document.querySelectorAll('[aria-invalid="true"], [class*="error" i], [role=alert]'))
            .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
            .map(e => (e.innerText || e.getAttribute('aria-label') || e.name || '').trim()).filter(Boolean).slice(0, 10)"""
        out = []
        for frame in self._frames(page):
            try:
                out.extend(frame.evaluate(js))
            except Exception:
                pass
        return out

    def _page_text(self, page) -> str:
        parts = []
        for frame in self._frames(page):
            try:
                parts.append(frame.evaluate("() => document.body ? document.body.innerText : ''"))
            except Exception:
                pass
        return "\n".join(parts)

    # ------------------------------------------------------------------ filling
    def _fill_one(self, frame, item: dict, value: str, files: dict[str, Path]) -> bool:
        sel = f'[data-ab="{item["n"]}"]'
        kind = item["kind"]
        loc = frame.locator(sel)
        try:
            if kind == "file":
                path = files.get(value)
                if not path:
                    return False
                loc.first.set_input_files(str(path))
                return True
            if kind in ("text", "email", "tel", "url", "number", "textarea", "date", "month"):
                loc.first.fill(str(value))
                return True
            if kind in ("select", "multiselect"):
                values = _as_list(value) if kind == "multiselect" else [value]
                chosen = [c for c in (choose_option(v, item["options"] or []) for v in values) if c]
                if not chosen:
                    return False
                loc.first.select_option(label=chosen if kind == "multiselect" else chosen[0])
                return True
            if kind == "radio":
                chosen = choose_option(value, item["options"] or [])
                if chosen is None:
                    return False
                idx = item["options"].index(chosen)
                frame.locator(f'{sel}[data-ab-opt="{idx}"]').first.check(force=True)
                return True
            if kind == "checkbox_group":
                ok = False
                for v in _as_list(value):
                    chosen = choose_option(v, item["options"] or [])
                    if chosen is not None:
                        frame.locator(f'{sel}[data-ab-opt="{item["options"].index(chosen)}"]').first.check(force=True)
                        ok = True
                return ok
            if kind == "checkbox":
                want = str(value).strip().lower() in ("yes", "true", "y", "1", "checked", "agree", "i agree")
                el = loc.first
                if not el.is_visible():
                    # Ashby-style yes/no: a hidden checkbox driven by "Yes" / "No" buttons next to it
                    if el.evaluate(self._YESNO_JS, "yes" if want else "no"):
                        return True
                if want:
                    el.check(force=True)
                return True
            if kind == "combobox":
                return self._fill_combobox(frame, loc.first, str(value), item)
            if kind == "yesno":
                chosen = choose_option(value, item["options"] or [])
                if chosen is None:
                    return False
                idx = item["options"].index(chosen)
                frame.locator(f'{sel} [data-ab-opt="{idx}"]').first.click()
                frame.page.wait_for_timeout(250)
                return bool(loc.first.evaluate(self._YESNO_PICKED_JS, idx))
        except Exception as e:
            self.log(f"[yellow]  could not fill '{item.get('label')}' ({kind}): {str(e).splitlines()[0][:120]}[/yellow]")
        return False

    _YESNO_PICKED_JS = """(grp, idx) => {
        const btns = Array.from(grp.querySelectorAll('[data-ab-opt]'));
        const b = btns[idx], other = btns[1 - idx];
        if (!b) return false;
        if (b.getAttribute('aria-pressed') === 'true' || /active|selected|checked/i.test(b.className)) return true;
        if (!other) return false;
        const bg = e => getComputedStyle(e).backgroundColor, fg = e => getComputedStyle(e).color;
        return bg(b) !== bg(other) || fg(b) !== fg(other);   // the picked button is styled differently
    }"""

    _YESNO_JS = """(el, want) => {
        let p = el.parentElement;
        for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
            const btns = Array.from(p.querySelectorAll('button')).filter(b => /^(yes|no)$/i.test((b.innerText || '').trim()));
            if (btns.length >= 2) {
                const b = btns.find(x => x.innerText.trim().toLowerCase() === want);
                if (b) { b.click(); return true; }
                return false;
            }
        }
        return false;
    }"""

    _COMBO_SHOWS_JS = """(el, want) => {
        const n = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
        const w = n(want);
        if (n(el.value) === w) return true;
        let p = el.parentElement;
        for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
            const c = p.cloneNode(true);
            c.querySelectorAll('label, legend, [role=listbox], [role=option]').forEach(x => x.remove());
            const t = n(c.innerText || c.textContent);
            if (t === w || t.split(/\\s{2,}|\\n/).some(x => n(x) === w) || (w.length > 3 && t.includes(w))) return true;
            // shown text can be a short form of the option ("United States +1" shows "+1")
            if (w.length >= 6 && t.split(/\\s{2,}|\\n/).map(n).some(x => x.length >= 2 && x !== 'select...' && w.includes(x))) return true;
            if (p.querySelector('label') && p.querySelectorAll('input, select, textarea').length > 2) break;
        }
        return false;
    }"""

    def _fill_combobox(self, frame, el, value: str, item: dict) -> bool:
        """Type into a searchable dropdown, pick the matching option from THIS field's listbox, then verify the
        field actually shows it (a wrong pick on a legal question is worse than no pick)."""
        page = frame.page
        try:
            page.keyboard.press("Escape")  # close any menu still open from the previous field
        except Exception:
            pass
        el.click()
        words = value.split()
        tries = [value] + [" ".join(words[:k]) for k in (3, 2, 1) if len(words) > k] + [""]  # "" = full list
        for t in tries:
            el.fill("")
            el.press_sequentially(t, delay=25)
            page.wait_for_timeout(700)
            lb = el.get_attribute("aria-controls") or el.get_attribute("aria-owns")
            opts = frame.locator(f'[id="{lb}"] [role=option]') if lb else frame.locator("[role=option]:visible")
            texts = [opts.nth(i).inner_text().strip() for i in range(min(opts.count(), 50))]
            chosen = choose_option(value, texts) if texts else None
            if chosen is None and texts and t and t != value:
                chosen = choose_option(t, texts)
            if chosen is None:
                continue
            opts.nth(texts.index(chosen)).click()
            page.wait_for_timeout(300)
            if el.evaluate(self._COMBO_SHOWS_JS, chosen):
                return True
            self.log(f"[yellow]  '{item.get('label', '')[:60]}': picked '{chosen}' but could not confirm it - "
                     f"left for review[/yellow]")
            return False
        el.fill("")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    def _upload_files(self, page, files: dict[str, Path], answers_log: dict) -> bool:
        """Upload resume / cover letter / transcript one at a time, rescanning after each (uploads change the DOM)."""
        done: set[str] = set()
        resume_done = False
        for _ in range(4):
            file_items = [(fr, it) for fr, it in self._scan(page) if it["kind"] == "file" and not it.get("value")]
            pick = None
            for frame, item in file_items:
                cat = classify(item.get("label", "") + " " + item.get("name", ""), "file")
                target = {"resume_file": "resume", "cover_letter": "cover_letter",
                          "transcript_file": "transcript"}.get(cat or "")
                if target is None and not resume_done and len(file_items) == 1:
                    target = "resume"
                if target and target in files and target not in done:
                    pick = (frame, item, target)
                    break
            if pick is None:
                break
            frame, item, target = pick
            done.add(target)
            if self._fill_one(frame, item, target, files):
                answers_log[item.get("label") or target] = f"<uploaded {files[target].name}>"
                resume_done = resume_done or target == "resume"
                page.wait_for_timeout(2500 if target == "resume" else 1000)
        return resume_done

    def fill_page(self, page, job: dict, files: dict[str, Path]) -> tuple[dict, list[str]]:
        """Fill every control on the current page. Returns (answers_log, unresolved_required_questions)."""
        answers_log: dict[str, str] = {}
        # Upload files first: many ATS parse the resume and auto-fill fields. Uploads change the DOM, so the
        # fields are scanned only AFTER all uploads - element numbers from an earlier scan would point at the
        # wrong inputs.
        self._upload_files(page, files, answers_log)

        fields, index = [], {}
        for frame, item in self._scan(page):
            if item["kind"] == "file":
                continue
            if item.get("value") and item["kind"] not in ("checkbox",):
                continue  # already filled (e.g. pre-populated after resume parsing)
            key = f"{id(frame)}:{item['n']}"
            fields.append(Field(key=key, kind=item["kind"], label=item.get("label", ""), required=item["required"],
                                options=item.get("options"), name=item.get("name", ""),
                                placeholder=item.get("placeholder", "")))
            index[key] = (frame, item)

        resolutions: dict[str, Resolution] = resolve_fields(fields, self.bank, self.profile, job, self.llm,
                                                            ask_human=self.ask_human)
        unresolved = []
        for f in fields:
            r = resolutions[f.key]
            frame, item = index[f.key]
            sensitive = bool(r.category and r.category.startswith(SENSITIVE_PREFIXES))
            if r.value is None:
                if f.required:
                    unresolved.append(f.question)
                continue
            ok = self._fill_one(frame, item, r.value, files)
            answers_log[f.question] = f"{r.value}  [{r.source}]" + ("" if ok else "  (NOT FILLED)")
            if not ok and (f.required or sensitive):  # never submit with a legal/EEO answer we couldn't place
                unresolved.append(f.question)
        return answers_log, unresolved

    # ------------------------------------------------------------------ main flow
    def apply(self, url: str, job: dict, files: dict[str, Path], mode: str, shot_dir: Path) -> ApplyResult:
        shot_dir.mkdir(parents=True, exist_ok=True)
        site = account_site(url)
        if site and (mode != "review" or not self.interactive):
            return ApplyResult(status="needs_review", final_url=url,
                               notes=f"{site} needs you to sign in - apply yourself with the tailored resume in {shot_dir}")
        page = self._ctx.new_page()
        result = ApplyResult(status="failed")
        all_answers: dict[str, str] = {}
        try:
            page.goto(direct_form_url(url), wait_until="domcontentloaded", timeout=60000)
            self._settle(page)
            page = self._open_form(page)

            max_steps = int(self.acfg.get("max_steps", 8))
            for step in range(max_steps):
                if self.detect_login(page) and len([i for _, i in self._scan(page) if i["kind"] != "file"]) <= 3:
                    if mode == "auto" or not self.interactive:
                        return self._finish(page, result, "needs_review", "login/account required", shot_dir,
                                            all_answers)
                    self._pause("This site needs you to sign in or create an account. Do it in the browser window, "
                                "navigate to the application form, then continue.", [("", "I'm on the form - continue")])
                    self._settle(page, 500)
                    page = self._latest_page(page)

                answers, unresolved = self.fill_page(page, job, files)
                all_answers.update(answers)
                self.log(f"  step {step + 1}: filled {len(answers)} field(s)"
                         + (f", [yellow]{len(unresolved)} unresolved[/yellow]" if unresolved else ""))

                submit = self._find_button(page, SUBMIT_RE)
                nxt = None if submit else self._find_button(page, NEXT_RE)
                if nxt is not None:
                    if unresolved and mode == "auto":
                        return self._finish(page, result, "needs_review",
                                            "unanswered required: " + "; ".join(unresolved[:5]), shot_dir, all_answers)
                    nxt.click()
                    self._settle(page)
                    page = self._latest_page(page)
                    continue

                if submit is None:
                    if mode == "review" and self.interactive:
                        resp = self._pause("No submit button detected. Finish the application in the browser window.",
                                           [("done", "I submitted it myself"), ("", "Skip (mark for review)")])
                        status = "applied" if resp == "done" else "needs_review"
                        return self._finish(page, result, status, "completed manually" if status == "applied"
                                            else "no submit button found", shot_dir, all_answers)
                    return self._finish(page, result, "needs_review", "no submit button found", shot_dir, all_answers)

                if not all_answers:
                    return self._finish(page, result, "needs_review", "no application form found on the page",
                                        shot_dir, all_answers)
                return self._submit(page, submit, mode, unresolved, result, shot_dir, all_answers)

            return self._finish(page, result, "needs_review", f"exceeded {max_steps} form steps", shot_dir,
                                all_answers)
        except Exception as e:
            return self._finish(page, result, "failed", f"{type(e).__name__}: {str(e).splitlines()[0][:300]}",
                                shot_dir, all_answers)
        finally:
            try:
                page.close()
            except Exception:
                pass

    def _latest_page(self, page):
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        return pages[-1] if pages else page

    def _open_form(self, page):
        """If the page is a job description rather than a form, click its Apply button."""
        fields = [i for _, i in self._scan(page) if i["kind"] not in ("file",)]
        if len(fields) >= 3:
            return page
        btn = self._find_button(page, APPLY_RE)
        if btn is None:
            return page
        before = len(self._ctx.pages)
        btn.click()
        self._settle(page)
        if len(self._ctx.pages) > before:
            page = self._ctx.pages[-1]
            self._settle(page)
        return page

    def _submit(self, page, submit, mode, unresolved, result, shot_dir, answers) -> ApplyResult:
        if mode == "dry_run":
            return self._finish(page, result, "dry_run", "stopped before submit (dry run)"
                                + (f"; unresolved: {'; '.join(unresolved[:5])}" if unresolved else ""),
                                shot_dir, answers)
        if self.detect_captcha(page):
            if mode == "auto" or not self.interactive:
                return self._finish(page, result, "needs_review", "CAPTCHA present", shot_dir, answers)
            self._pause("A CAPTCHA is shown - please solve it in the browser window, then continue.",
                        [("", "Solved - continue")])
        if mode == "review":
            if not self.interactive:
                return self._finish(page, result, "needs_review", "review mode without a terminal", shot_dir, answers)
            self.log("\n[bold]Answers filled:[/bold]")
            for q, a in answers.items():
                self.log(f"  - {q[:80]}: {str(a)[:100]}")
            if unresolved:
                self.log(f"[yellow]  Unresolved required fields: {unresolved}[/yellow]")
            resp = self._pause("Review the form in the browser window (edit anything you like). Submit now?",
                               [("y", "Submit"), ("m", "I submitted it manually"), ("n", "Skip")],
                               {"answers": answers, "unresolved": unresolved})
            if resp == "m":
                return self._finish(page, result, "applied", "submitted manually by user", shot_dir, answers)
            if resp != "y":
                return self._finish(page, result, "skipped", "user skipped at review", shot_dir, answers)
        elif unresolved:
            return self._finish(page, result, "needs_review", "unanswered required: " + "; ".join(unresolved[:5]),
                                shot_dir, answers)

        submit.click()
        self._settle(page, 3000)
        page = self._latest_page(page)
        text = self._page_text(page)
        if CONFIRM_RE.search(text):
            return self._finish(page, result, "applied", "confirmation detected", shot_dir, answers)
        errors = self._errors(page)
        if errors:
            if mode == "review" and self.interactive:
                resp = self._pause(f"The form reported problems: {errors[:3]}. Fix and submit in the browser window.",
                                   [("done", "Fixed & submitted"), ("", "Mark for review")])
                if resp == "done":
                    return self._finish(page, result, "applied", "fixed & submitted by user", shot_dir, answers)
            return self._finish(page, result, "needs_review", f"form errors: {errors[:3]}", shot_dir, answers)
        if mode == "review" and self.interactive:
            resp = self._pause("Submitted, but no confirmation message was detected. Did the application go through?",
                               [("done", "Yes, it was submitted"), ("", "Not sure - mark for review")])
            if resp == "done":
                return self._finish(page, result, "applied", "submitted; confirmed by user", shot_dir, answers)
        return self._finish(page, result, "needs_review", "clicked submit but no confirmation was detected - check it",
                            shot_dir, answers)

    def _finish(self, page, result: ApplyResult, status: str, notes: str, shot_dir: Path,
                answers: dict) -> ApplyResult:
        result.status, result.notes, result.answers = status, notes, answers
        try:
            result.final_url = page.url
            shot = shot_dir / f"{status}_{int(time.time())}.png"
            page.screenshot(path=str(shot), full_page=True)
            result.screenshot = str(shot)
        except Exception:
            pass
        return result


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    s = str(value).strip()
    if s.startswith("["):
        try:
            return [str(v) for v in json.loads(s)]
        except json.JSONDecodeError:
            pass
    return [p.strip() for p in re.split(r"[;,]\s*", s) if p.strip()]
