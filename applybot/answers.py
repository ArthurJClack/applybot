"""Resolve application form questions to answers.

Order of resolution for each field:
  1. Deterministic rules (name, email, phone, links, education...) from the profile and answers.yaml
  2. Your saved/learned answers in answers.yaml (fuzzy question matching)
  3. AI (only for non-sensitive questions - never for legal, EEO/demographic, or attestation questions)
  4. Ask you in the terminal (review mode) - your answer is saved for next time
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from applybot.llm import LLM, LLMError
from applybot.profile import profile_to_text, split_name

DEFAULT_ANSWERS = {
    "basics": {"preferred_name": "", "pronouns": "", "address": "", "city": "", "state": "", "zip": "",
               "country": "United States", "current_company": "", "current_title": "", "years_experience": ""},
    "work_authorization": {"authorized_to_work": "", "requires_sponsorship": ""},
    "logistics": {"start_date": "", "salary_expectation": "", "willing_to_relocate": "Yes", "notice_period": "",
                  "how_did_you_hear": "Online job board", "in_person_ok": "Yes"},
    "eeo": {"gender": "Decline to self-identify", "race": "Decline to self-identify",
            "hispanic_latino": "Decline to self-identify", "veteran": "",
            "disability": "I do not want to answer", "sexual_orientation": "Decline to self-identify",
            "transgender": "Decline to self-identify"},
    "sensitive": {"over_18": "", "criminal_conviction": "", "previously_employed_here": "",
                  "non_compete": "", "background_check_ok": "", "drug_test_ok": ""},
    "auto_consent": False,
    "files": {"transcript": ""},
    "custom": {},
    "learned": {},
}


def qnorm(s: str) -> str:
    s = re.sub(r"\*|\(required\)|\(optional\)", "", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@dataclass
class Field:
    key: str
    kind: str  # text|email|tel|url|number|date|textarea|select|radio|checkbox|checkbox_group|file|combobox
    label: str
    required: bool = False
    options: list[str] | None = None
    name: str = ""
    placeholder: str = ""

    @property
    def question(self) -> str:
        return self.label or self.placeholder or self.name


# (category, regex) - order matters, first match wins
RULES: list[tuple[str, str]] = [
    ("consent", r"\b(i (agree|acknowledge|consent|certify|confirm|understand|attest))|i am certifying|i hereby certify|i hereby affirm|review and acknowledge|privacy acknowledgement|privacy (policy|notice)|terms (and|&) conditions|consent to"),
    ("resume_file", r"\b(resume|r[eé]sum[eé]|cv)\b"),
    ("cover_letter", r"cover\s*letter"),
    ("transcript_file", r"transcript"),
    ("eeo.gender", r"\bgender\b|\bsex\b"),
    ("eeo.transgender", r"transgender"),
    ("eeo.sexual_orientation", r"sexual orientation"),
    ("eeo.hispanic_latino", r"hispanic|latin[oa]"),
    ("eeo.race", r"\brace\b|ethnicity|racial"),
    ("eeo.veteran", r"veteran|military service"),
    ("eeo.disability", r"disabilit"),
    ("basics.pronouns", r"pronoun"),
    ("work_authorization.requires_sponsorship", r"sponsor|visa status|h-?1b|immigration"),
    ("work_authorization.authorized_to_work", r"authori[sz]ed to work|eligible to work|legally (permitted|able|allowed)|right to work|work authori[sz]ation"),
    ("sensitive.over_18", r"(18|eighteen) years|at least 18|over the age|legal age"),
    ("sensitive.criminal_conviction", r"convict|felony|criminal|misdemeanor"),
    ("sensitive.previously_employed_here", r"(previously|ever|formerly) (been )?(employed|worked)|former employee|worked (for|at) .* before|current employee of|^have you (ever )?worked (at|for)\b|current or former .{0,40}employee"),
    ("sensitive.non_compete", r"non-?compete|restrictive covenant|non-?solicit"),
    ("sensitive.background_check_ok", r"background check"),
    ("sensitive.drug_test_ok", r"drug (test|screen)"),
    ("first_name", r"^(legal )?first name|^given name|first name\b"),
    ("last_name", r"^(legal )?last name|surname|family name|last name\b"),
    ("basics.preferred_name", r"preferred (first )?name|nickname|chosen name"),
    ("full_name", r"^(full |legal )?name$|^your name|full name|legal name|signature"),
    ("email", r"e-?mail"),
    ("phone", r"\b(phone|mobile|cell)\b"),
    ("linkedin", r"linked\s*in"),
    ("github", r"github"),
    ("website", r"website|portfolio|personal (site|url|page)|blog|other (url|link)"),
    ("basics.zip", r"zip|postal"),
    ("basics.address", r"street|address line|^address"),
    ("basics.city", r"^city|current city|city\b"),
    ("basics.state", r"^state|province|region"),
    ("basics.country", r"country"),
    ("logistics.willing_to_relocate", r"relocat"),
    ("logistics.in_person_ok", r"in[- ]office requirement|willing (and able )?to work in the location|able to work (in|at|from) (the |our )?(office|location)"),
    ("location", r"location|where (are you|do you) (based|live|located)|current(ly)? (located|residing)"),
    ("edu_start_month", r"^start date month"),
    ("edu_start_year", r"^start date year"),
    ("grad_month", r"end date month|graduation month|month of graduation|end month"),
    ("grad_year", r"end date year|graduation year|year of graduation|end year|class year"),
    ("graduation", r"graduat|completion date|expected (grad|completion)|class of"),
    ("school", r"school|university|college|institution"),
    ("degree", r"degree( type| level)?$|level of education|highest (degree|education)"),
    ("major", r"major|field of study|discipline|area of study|concentration"),
    ("gpa", r"\bgpa\b|grade point"),
    ("basics.current_company", r"current (company|employer)|most recent (company|employer)|candidate'?s company"),
    ("basics.current_title", r"current (title|role|position)|most recent (title|role)|current or previous (job )?title|previous job title"),
    ("basics.years_experience", r"years of (professional )?experience|how many years"),
    ("logistics.start_date", r"start date|when can you start|available to start|availability"),
    ("logistics.salary_expectation", r"salary|compensation|pay (expectation|requirement)|desired pay"),
    ("logistics.notice_period", r"notice period"),
    ("logistics.in_person_ok", r"in[- ]person|on[- ]?site|in[- ]office|hybrid|commute"),
    ("logistics.how_did_you_hear", r"how did you (hear|find|learn)|where did you (hear|find|see)|referral source|^source$|what brought you to|how you heard about"),
]

SENSITIVE_PREFIXES = ("eeo.", "sensitive.", "work_authorization.")


OPEN_ENDED_RE = re.compile(
    r"^\s*(please\s+)?(describe|tell (us|me)|explain|share|discuss|elaborate|walk us|give (us )?an example|"
    r"what (makes|excites|interests|motivates|draws|is a|was a|are some)|why |how (would|do|did|have) you)", re.I)
# Categories that may still apply to an open-ended prompt (they answer with a document or a long text).
LONG_OK = {"cover_letter", "resume_file", "transcript_file", "consent"}


_NOT_OPEN = re.compile(r"how did you (hear|find|learn|come across)|what brought you to|how you heard about", re.I)


def is_open_ended(question: str, kind: str = "") -> bool:
    q = (question or "").strip()
    if _NOT_OPEN.search(q):
        return False
    return bool(OPEN_ENDED_RE.search(q)) or (kind == "textarea" and len(q.split()) > 6)


def classify(question: str, kind: str = "") -> str | None:
    q = (question or "").lower().replace("_", " ")
    q = re.sub(r"\s*(\*|\u2731|\(required\))\s*$", "", q.strip())  # "Degree*" -> "degree"
    open_ended = is_open_ended(question, kind)
    for cat, pattern in RULES:
        if open_ended and cat not in LONG_OK:
            continue
        if re.search(pattern, q):
            return cat
    return None


_NO_RE = re.compile(r"^(no|not|none|i am not|i m not|i do not|i don t|i will not|i won t|i have not|i haven t|false)\b")
_YES_RE = re.compile(r"^(yes|i am|i m|i do|i will|i have|true|authorized|agree|i agree|accept)\b")
_DECLINE = ("decline", "prefer not", "not to answer", "do not want", "don t wish", "not wish", "choose not",
            "not to disclose", "not to self identify")


_ALIASES = {"male": ("man", "cisgender man", "cis man"), "female": ("woman", "cisgender woman", "cis woman"),
            "man": ("male",), "woman": ("female",)}


def _polarity(s: str) -> str | None:
    n = qnorm(s)
    if _NO_RE.match(n):
        return "no"
    if _YES_RE.match(n):
        return "yes"
    return None


def choose_option(value: str, options: list[str]) -> str | None:
    """Map a desired answer onto one of a form's options."""
    if not options:
        return value
    opts = [o for o in options if o and qnorm(o) not in ("", "select", "select one", "select an option",
                                                         "please select", "choose", "choose one")]
    v = qnorm(str(value))
    if not v:
        return None
    for o in opts:
        if qnorm(o) == v:
            return o
    for alias in _ALIASES.get(v, ()):  # "Male" -> "Man", "Female" -> "Woman"
        for o in opts:
            if qnorm(o) == alias or qnorm(o).startswith(alias + " "):
                return o
    if any(w in v for w in _DECLINE):
        for o in opts:
            if any(w in qnorm(o) for w in _DECLINE):
                return o
    pol = _polarity(v)
    if pol and v in ("yes", "no", "true", "false"):
        for o in opts:
            if _polarity(o) == pol:
                return o
    for o in opts:
        on = qnorm(o)
        if on and (on.startswith(v) or v.startswith(on) or (len(v) > 3 and v in on)):
            return o
    best = difflib.get_close_matches(str(value), opts, n=1, cutoff=0.6)
    if best:
        return best[0]
    if pol:
        for o in opts:
            if _polarity(o) == pol:
                return o
    # "Online job board" -> "Job Board (e.g. Indeed)": >= 2 shared words, only for plain (non yes/no, non-decline)
    # answers so a legal answer can never be matched loosely
    words = {w for w in v.split() if len(w) > 2}
    if len(words) >= 2 and not pol and not any(w in v for w in _DECLINE):
        scored = sorted(((len(words & {w for w in qnorm(o).split() if len(w) > 2}), o) for o in opts
                         if _polarity(o) is None), key=lambda x: -x[0])
        if scored and scored[0][0] >= 2 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
            return scored[0][1]
    # GPA-style numeric answer vs range options ("3.5 - 4.0")
    if re.fullmatch(r"\d+(\.\d+)?", str(value).strip()):
        x = float(value)
        for o in opts:
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|\u2013|to)\s*(\d+(?:\.\d+)?)", o)
            if m and float(m.group(1)) <= x <= float(m.group(2)):
                return o
    # "June 2027" vs term options ("Spring 2027", "Summer 2027")
    md = re.fullmatch(r"([a-z]+) ((?:19|20)\d{2})", v)
    if md and md.group(1)[:3] in _MONTHS:
        mo, yr = _MONTHS[md.group(1)[:3]], md.group(2)
        terms = ["winter"] if mo <= 2 else ["spring", "summer"] if mo <= 6 else ["summer", "fall"] if mo <= 8 else ["fall"]
        for t in terms:
            for o in opts:
                on = qnorm(o)
                if t in on and yr in on:
                    return o
    return None


_NON_BOOLEAN = {"school", "degree", "major", "gpa", "logistics.start_date", "location", "basics.city", "basics.state",
                "basics.country", "basics.address", "basics.zip", "grad_month", "grad_year", "edu_start_month",
                "edu_start_year", "logistics.salary_expectation", "basics.current_company", "basics.current_title",
                "logistics.how_did_you_hear", "first_name", "last_name", "full_name", "email", "phone"}


def _strip_lead(q: str) -> str:
    """Drop a leading context sentence: 'The start date is in 2027. Are you able to...' -> 'Are you able to...'."""
    q = q or ""
    m = re.search(r"(?:^|[.?!:]\s+)((?:are|will|do|did|have|has|is|can|were|would)\s+you\b.*)$", q, re.I)
    return m.group(1) if m else q


YES_NO_Q = re.compile(r"^\s*(?:by [^,?]{1,30},\s*)?(are|will|do|did|have|has|is|can|were|would)\s+you\b", re.I)


def _degree_level(degree: str) -> str:
    """'B.S. Computer Science' -> "Bachelor's" (what degree dropdowns list)."""
    d = (degree or "").strip().lower()
    if re.match(r"(b\.?\s?[sae]\.?|b\.?eng|bachelor)", d):
        return "Bachelor's"
    if re.match(r"(m\.?\s?[sae]\.?|m\.?eng|master|mba)", d):
        return "Master's"
    if re.match(r"(ph\.?d|doctor)", d):
        return "Doctorate"
    if re.match(r"(a\.?\s?[as]\.?|associate)", d):
        return "Associate's"
    return ""


_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"), 1)}


def _ym(text: str) -> list[tuple[int, int]]:
    out = []
    for mon, yr in re.findall(r"(?:([A-Za-z]{3,})\.?\s+)?((?:19|20)\d{2})", text or ""):
        out.append((int(yr), _MONTHS.get(mon[:3].lower(), 0) if mon else 0))
    return out


def _graduation_yes_no(question: str, grad: str) -> str | None:
    """'Are you projected to graduate between May 2026 and December 2029?' with grad 'June 2027' -> 'Yes'."""
    g = _ym(grad)
    rng = _ym(question)
    if not g or len(rng) != 2:
        return None
    (gy, gm), (ay, am), (by, bm) = g[0], rng[0], rng[1]
    if not gm:
        inside = ay <= gy <= by
    else:
        inside = (ay, am or 1) <= (gy, gm) <= (by, bm or 12)
    return "Yes" if inside else "No"


class AnswerBank:
    def __init__(self, path: str | Path, profile: dict, resume_text: str = "", cover_letter_text: str = ""):
        self.path = Path(path)
        data = {}
        if self.path.exists():
            data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.data = json.loads(json.dumps(DEFAULT_ANSWERS))
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(self.data.get(k), dict):
                self.data[k].update({kk: vv for kk, vv in v.items() if vv is not None})
            elif v is not None:
                self.data[k] = v
        self.profile = profile
        self.cover_letter_text = cover_letter_text
        self.resume_text = resume_text

    # ------------------------------------------------------------------ deterministic values
    def _get(self, dotted: str) -> str:
        section, key = dotted.split(".", 1)
        return str(self.data.get(section, {}).get(key) or "")

    def _profile_value(self, cat: str) -> str:
        c = self.profile.get("contact", {})
        edu = (self.profile.get("education") or [{}])[0]
        first, last = split_name(self.profile)
        loc = c.get("location", "")
        loc_parts = [x.strip() for x in loc.split(",")]
        degree = edu.get("degree", "")
        major = ""
        m = re.match(r"^(B\.?S\.?|B\.?A\.?|M\.?S\.?|M\.?A\.?|Ph\.?D\.?|B\.?Eng\.?|M\.?Eng\.?|MBA|Bachelor[\w']*"
                     r"(?: of \w+)?|Master[\w']*(?: of \w+)?|Associate[\w']*(?: of \w+)?)\s*(?:in|of|,)?\s*(.*)$",
                     degree, re.I)
        if m:
            major = m.group(2)
        grad = start = ""
        if edu.get("dates") and re.search(r"\s[-\u2013\u2014]\s|\sto\s", edu["dates"]):
            start = re.split(r"\s*[-\u2013\u2014]\s*|\s+to\s+", edu["dates"])[0].strip()
        if edu.get("dates"):
            grad = re.split(r"\s*[-\u2013\u2014]\s*|\s+to\s+", edu["dates"])[-1].replace("Expected", "").strip()
        values = {
            "first_name": first, "last_name": last, "full_name": c.get("name", ""),
            "email": c.get("email", ""), "phone": c.get("phone", ""), "linkedin": c.get("linkedin", ""),
            "github": c.get("github", ""), "website": c.get("website", "") or c.get("github", ""),
            "location": loc, "basics.city": loc_parts[0] if loc_parts else "",
            "basics.state": loc_parts[1] if len(loc_parts) > 1 else "",
            "school": edu.get("school", ""), "degree": degree, "major": major, "gpa": edu.get("gpa", ""),
            "graduation": grad,
            "edu_start_month": (re.search(r"[A-Za-z]{3,}", start) or [""])[0] if start else "",
            "edu_start_year": (re.search(r"(19|20)\d{2}", start) or [""])[0] if start else "",
            "grad_month": (re.search(r"[A-Za-z]{3,}", grad) or [""])[0] if grad else "",
            "grad_year": (re.search(r"(19|20)\d{2}", grad) or [""])[0] if grad else "",
            "degree_level": _degree_level(degree),
        }
        return values.get(cat, "")

    def rule_answer(self, field: Field) -> tuple[str | None, str | None]:
        """Returns (value, category). value None means 'no deterministic answer'."""
        cat = classify(field.question, field.kind)
        if cat is None:
            return None, None
        if cat == "graduation" and YES_NO_Q.match(field.question or ""):
            return _graduation_yes_no(field.question, self._profile_value("graduation")), cat
        if YES_NO_Q.match(_strip_lead(field.question)) and cat in _NON_BOOLEAN:
            return None, cat
        if cat == "degree" and field.kind in ("combobox", "select", "radio"):
            return (self._profile_value("degree_level") or self._profile_value("degree") or None), cat
        if cat in ("resume_file", "transcript_file"):
            return (None, cat) if field.kind != "file" else ("__FILE__", cat)
        if cat == "cover_letter":
            if field.kind == "file":
                return "__FILE__", cat
            if field.kind in ("text", "textarea"):
                return self.cover_letter_text or None, cat
            return None, cat
        if cat == "consent":
            if not self.data.get("auto_consent"):
                return None, cat
            if field.kind in ("text", "textarea"):  # e.g. "type your full name to certify"
                return self.profile.get("contact", {}).get("name") or None, cat
            return "Yes", cat
        if "." in cat:
            val = self._get(cat) or self._profile_value(cat)
            if not val and cat == "basics.preferred_name":
                val = split_name(self.profile)[0]
            return (val or None), cat
        return (self._profile_value(cat) or None), cat

    def saved_answer(self, question: str) -> str | None:
        qn = qnorm(question)
        if not qn:
            return None
        for section in ("custom", "learned"):
            bank = self.data.get(section) or {}
            for q, a in bank.items():
                kn = qnorm(q)
                if not kn:
                    continue
                if kn == qn or (section == "custom" and re.search(r"(?<![a-z0-9])" + re.escape(kn) + r"(?![a-z0-9])", qn)):
                    return str(a)
            match = difflib.get_close_matches(qn, [qnorm(q) for q in bank], n=1, cutoff=0.88)
            if match:
                for q, a in bank.items():
                    if qnorm(q) == match[0]:
                        return str(a)
        return None

    def learn(self, question: str, answer: str):
        self.data.setdefault("learned", {})[question.strip()] = answer
        self.save()

    def save(self):
        """Write answers back, keeping the comment header at the top of the file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        header = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.startswith("#") or (header and not line.strip()):
                    header.append(line)
                else:
                    break
        body = yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True)
        text = ("\n".join(header).rstrip() + "\n" if header else "") + body
        self.path.write_text(text, encoding="utf-8")


AI_FIELDS_PROMPT = """You are filling out a job/application form on behalf of the candidate.
For each field, give the answer the candidate would give. Rules:
- Use ONLY facts from the candidate data. Never invent experience, credentials, numbers, or personal details.
- For open-ended questions (e.g. "why this company", "describe a project"), write a genuine, specific 60-150 word
  answer grounded in the candidate's real experience and the posting.
- For fields with options, answer with EXACTLY one of the provided options (for checkbox groups, a JSON list).
- If the candidate data does not contain the answer and it cannot be reasonably composed, answer "__UNKNOWN__".

Return JSON: {{"answers": {{"<field key>": "<answer>"}}}}

CANDIDATE:
{profile}

POSITION:
{job}

FIELDS:
{fields}"""


def ai_answers(fields: list[Field], profile: dict, job: dict, llm: LLM) -> dict[str, str]:
    if not fields or not llm.available:
        return {}
    payload = [{"key": f.key, "question": f.question, "type": f.kind, "required": f.required,
                **({"options": f.options[:60]} if f.options else {})} for f in fields]
    job_txt = json.dumps({k: job.get(k) for k in ("company", "title", "location")}) + "\n" + \
        (job.get("description") or "")[:5000]
    try:
        data = llm.complete_json(AI_FIELDS_PROMPT.format(profile=profile_to_text(profile)[:10000], job=job_txt,
                                                         fields=json.dumps(payload, indent=1)),
                                 system="You complete application forms accurately and honestly.")
    except LLMError:
        return {}
    answers = data.get("answers", data) if isinstance(data, dict) else {}
    out = {}
    for k, v in answers.items():
        if isinstance(v, list):
            v = json.dumps(v)
        if v is not None and str(v).strip() and "__UNKNOWN__" not in str(v):
            out[str(k)] = str(v)
    return out


def terminal_prompt(field: Field) -> str | None:
    if not sys.stdin or not sys.stdin.isatty():
        return None
    opts = f"\n    options: {field.options}" if field.options else ""
    req = " (required)" if field.required else ""
    ans = input(f"\n  ? {field.question}{req}{opts}\n    your answer (blank = skip): ").strip()
    return ans or None


@dataclass
class Resolution:
    value: str | None
    source: str  # rule | saved | ai | human | none
    category: str | None = None


def resolve_fields(fields: list[Field], bank: AnswerBank, profile: dict, job: dict, llm: LLM | None,
                   ask_human: Callable[[Field], str | None] | None = None) -> dict[str, Resolution]:
    out: dict[str, Resolution] = {}
    pending: list[Field] = []
    for f in fields:
        saved = bank.saved_answer(f.question) if f.kind != "file" else None
        val, cat = bank.rule_answer(f)
        if saved:  # your explicit/learned answers always win
            out[f.key] = Resolution(saved, "saved", cat)
            continue
        if val is not None:
            out[f.key] = Resolution(val, "rule", cat)
            continue
        out[f.key] = Resolution(None, "none", cat)
        if f.kind == "file" or cat == "consent" or (cat and cat.startswith(SENSITIVE_PREFIXES)):
            continue  # never let AI guess legal, demographic, or attestation answers
        pending.append(f)

    if pending and llm is not None:
        for key, val in ai_answers(pending, profile, job, llm).items():
            if key in out:
                out[key] = Resolution(val, "ai", out[key].category)

    if ask_human:
        for f in fields:
            r = out[f.key]
            if r.value is None and f.required and f.kind != "file":
                ans = ask_human(f)
                if ans:
                    out[f.key] = Resolution(ans, "human", r.category)
                    bank.learn(f.question, ans)
    return out
