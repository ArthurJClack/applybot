"""Load the candidate's information from a plain text file.

Two parsing modes:
  * structured - a simple, documented markdown-ish format (see profile.example.txt). Deterministic, no AI.
  * ai         - free-form text of any shape; the AI extracts it into the same schema.
`auto` uses the structured parser when the file has recognised '# Section' headers, otherwise AI.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from applybot.llm import LLM

SECTION_ALIASES = {
    "contact": "contact", "contact info": "contact", "personal": "contact", "info": "contact",
    "summary": "summary", "about": "summary", "objective": "summary", "profile": "summary",
    "education": "education",
    "experience": "experience", "work experience": "experience", "employment": "experience", "work": "experience",
    "projects": "projects", "project": "projects",
    "skills": "skills", "technical skills": "skills",
    "certifications": "certifications", "certificates": "certifications",
    "awards": "awards", "honors": "awards", "awards and honors": "awards", "achievements": "awards",
    "leadership": "leadership", "activities": "leadership", "extracurriculars": "leadership",
    "volunteering": "leadership", "involvement": "leadership",
    "preferences": "preferences", "application answers": "preferences", "logistics": "preferences",
    "other": "other", "notes": "other", "additional": "other", "additional info": "other",
}

EMPTY_PROFILE: dict[str, Any] = {
    "contact": {"name": "", "email": "", "phone": "", "location": "", "linkedin": "", "github": "", "website": ""},
    "summary": "",
    "education": [],     # {school, degree, location, dates, gpa, details[]}
    "experience": [],    # {title, company, location, dates, bullets[]}
    "projects": [],      # {name, tech, link, dates, bullets[]}
    "leadership": [],    # same shape as experience
    "skills": [],        # {category, items[]}
    "certifications": [],
    "awards": [],
    "preferences": {},
    "other": "",
}

DATE_RE = re.compile(
    r"((jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}|\b(19|20)\d{2}\b|present|current|expected)",
    re.I)
BULLET_RE = re.compile(r"^\s*([-*\u2022\u25aa\u25cf]|\d+[.)])\s+")


def _blank_profile() -> dict:
    return json.loads(json.dumps(EMPTY_PROFILE))


def _split_sections(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for line in text.splitlines():
        m = re.match(r"^\s*#{1,3}\s*(.+?)\s*#*\s*$", line)
        if m:
            name = re.sub(r"\(.*?\)", "", m.group(1)).strip().lower().rstrip(":")
            current = (SECTION_ALIASES.get(name, name), [])
            sections.append(current)
        elif current is not None:
            current[1].append(line.rstrip())
    return sections


def _entries(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Group lines into (header, bullets) entries. A non-bullet line starts a new entry."""
    out: list[tuple[str, list[str]]] = []
    for line in lines:
        if not line.strip():
            continue
        if BULLET_RE.match(line):
            bullet = BULLET_RE.sub("", line).strip()
            if out:
                out[-1][1].append(bullet)
            else:
                out.append(("", [bullet]))
        elif out and line.startswith(("  ", "\t")) and out[-1][1]:
            out[-1][1][-1] += " " + line.strip()  # wrapped bullet continuation
        else:
            out.append((line.strip(), []))
    return out


def _parts(header: str) -> list[str]:
    return [p.strip() for p in re.split(r"\s+\|\s+|\s+\u2014\s+|\t", header) if p.strip()]


def _is_date(s: str) -> bool:
    return bool(DATE_RE.search(s)) and len(s) < 40


def _kv(lines: list[str]) -> dict[str, str]:
    out = {}
    for line in lines:
        line = BULLET_RE.sub("", line).strip()
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def parse_structured(text: str) -> dict:
    p = _blank_profile()
    for name, lines in _split_sections(text):
        if name == "contact":
            for k, v in _kv(lines).items():
                key = k.lower().replace(" ", "")
                mapping = {"name": "name", "fullname": "name", "email": "email", "phone": "phone",
                           "location": "location", "address": "location", "linkedin": "linkedin",
                           "github": "github", "website": "website", "portfolio": "website", "site": "website"}
                if key in mapping:
                    p["contact"][mapping[key]] = v
                else:
                    p["contact"][k.strip()] = v
        elif name in ("summary", "other"):
            p[name] = "\n".join(lines).strip()
        elif name == "education":
            for header, bullets in _entries(lines):
                parts = _parts(header)
                e = {"school": parts[0] if parts else "", "degree": "", "location": "", "dates": "", "gpa": "",
                     "details": bullets}
                rest = []
                for part in parts[1:]:
                    if part.lower().startswith("gpa"):
                        e["gpa"] = part.split(":", 1)[-1].strip()
                    elif _is_date(part):
                        e["dates"] = part
                    else:
                        rest.append(part)
                if rest:
                    e["degree"] = rest[0]
                if len(rest) > 1:
                    e["location"] = rest[1]
                p["education"].append(e)
        elif name in ("experience", "leadership"):
            for header, bullets in _entries(lines):
                parts = _parts(header)
                e = {"title": parts[0] if parts else "", "company": "", "location": "", "dates": "",
                     "bullets": bullets}
                rest = []
                for part in parts[1:]:
                    if _is_date(part):
                        e["dates"] = part
                    else:
                        rest.append(part)
                if rest:
                    e["company"] = rest[0]
                if len(rest) > 1:
                    e["location"] = rest[1]
                p[name].append(e)
        elif name == "projects":
            for header, bullets in _entries(lines):
                parts = _parts(header)
                e = {"name": parts[0] if parts else "", "tech": "", "link": "", "dates": "", "bullets": bullets}
                for part in parts[1:]:
                    if re.match(r"https?://|www\.|github\.com", part):
                        e["link"] = part
                    elif _is_date(part):
                        e["dates"] = part
                    else:
                        e["tech"] = part
                p["projects"].append(e)
        elif name == "skills":
            for line in lines:
                line = BULLET_RE.sub("", line).strip()
                if not line:
                    continue
                if ":" in line:
                    cat, items = line.split(":", 1)
                else:
                    cat, items = "Skills", line
                p["skills"].append({"category": cat.strip(),
                                    "items": [i.strip() for i in re.split(r"[,;]", items) if i.strip()]})
        elif name in ("certifications", "awards"):
            p[name].extend(BULLET_RE.sub("", ln).strip() for ln in lines if ln.strip())
        elif name == "preferences":
            p["preferences"].update(_kv(lines))
        else:
            extra = "\n".join(lines).strip()
            if extra:
                p["other"] = (p["other"] + f"\n\n[{name}]\n{extra}").strip()
    return p


AI_PARSE_PROMPT = """Extract the candidate information below into this exact JSON schema.
Copy facts verbatim; do NOT invent, embellish, or infer anything that is not stated. Use "" or [] when missing.

{schema}

Notes:
- "preferences" holds application logistics as key/value strings (e.g. "Work Authorization", "Needs Sponsorship",
  "Desired Roles", "Start Date", "Salary Expectation", "Willing to Relocate", pronouns, etc.).
- "leadership" holds clubs, volunteering, and activities (same shape as experience).
- "other" holds any remaining useful information as plain text.

CANDIDATE TEXT:
<<<
{text}
>>>"""


def parse_with_ai(text: str, llm: LLM) -> dict:
    data = llm.complete_json(AI_PARSE_PROMPT.format(schema=json.dumps(EMPTY_PROFILE, indent=1), text=text),
                             system="You are a meticulous resume data extractor.")
    p = _blank_profile()
    if isinstance(data, dict):
        for k in p:
            if k in data and data[k] is not None:
                p[k] = data[k] if not isinstance(p[k], dict) else {**p[k], **data[k]}
    return p


def has_structured_sections(text: str) -> bool:
    names = {n for n, _ in _split_sections(text)}
    return len(names & {"contact", "experience", "education", "skills", "projects"}) >= 2


def load_profile(path: str | Path, llm: LLM | None = None, parser: str = "auto",
                 cache_path: str | Path | None = None, refresh: bool = False) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"profile file not found: {path} (run `applybot init`)")
    text = path.read_text(encoding="utf-8")
    digest = hashlib.sha256((parser + text).encode()).hexdigest()

    if cache_path and not refresh:
        cp = Path(cache_path)
        if cp.exists():
            cached = json.loads(cp.read_text(encoding="utf-8"))
            if cached.get("_hash") == digest:
                return cached["profile"]

    use_structured = parser == "structured" or (parser == "auto" and has_structured_sections(text))
    if use_structured:
        profile = parse_structured(text)
    elif llm is not None and llm.available:
        profile = parse_with_ai(text, llm)
    else:
        profile = parse_structured(text)
        profile["other"] = text  # keep everything available even if unstructured
    profile["raw"] = text

    if cache_path:
        cp = Path(cache_path)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({"_hash": digest, "profile": profile}, indent=2), encoding="utf-8")
    return profile


# ---------------------------------------------------------------------- helpers
def all_skills(profile: dict) -> list[str]:
    out: list[str] = []
    for group in profile.get("skills", []):
        out.extend(group.get("items", []))
    for proj in profile.get("projects", []):
        out.extend(t.strip() for t in re.split(r"[,;/]", proj.get("tech", "") or "") if t.strip())
    seen, uniq = set(), []
    for s in out:
        if s.lower() not in seen:
            seen.add(s.lower())
            uniq.append(s)
    return uniq


def split_name(profile: dict) -> tuple[str, str]:
    name = (profile.get("contact", {}).get("name") or "").strip()
    if not name:
        return "", ""
    parts = name.split()
    return parts[0], " ".join(parts[1:])


def profile_to_text(profile: dict, include_raw_other: bool = True) -> str:
    """Compact text rendering used in prompts."""
    p = {k: v for k, v in profile.items() if k != "raw" and v}
    if not include_raw_other:
        p.pop("other", None)
    return json.dumps(p, indent=1, ensure_ascii=False)


def short_term_hit(term: str, text: str) -> bool:
    """Very short skill names (Go, R, C) are also ordinary words/letters. Count one only when it sits in a
    tech-looking context: a list ("Python, Go, SQL"), after "with/in/and/using", or next to "and/or"."""
    import re
    for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9+#])", text):
        before = text[max(0, m.start() - 14):m.start()]
        after = text[m.end():m.end() + 14]
        if (re.search(r"[,/(|;:•·]\s*$", before) or re.match(r"\s*[,/)|;•·]", after)
                or re.search(r"\b(with|in|and|or|using|of|for)\s+$", before, re.I)
                or re.match(r"\s+(and|or)\b", after) or re.match(r"\s*(lang|programming)", after, re.I)):
            return True
    return False
