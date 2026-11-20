"""Built-in Seattle / Tacoma / Puget Sound company boards, merged into the greenhouse/lever/ashby sources.

Your config.yaml `companies` list replaces the defaults instead of extending them, so local employers
would never show up unless you typed every slug yourself. These boards are added on top of whatever
you configured. Turn them off per source with `pnw_boards: false`, e.g.

    search:
      sources:
        greenhouse:
          companies: [stripe]
          pnw_boards: false

Unknown or removed slugs are harmless: a 404 or a bad response just skips that one company.
"""
from __future__ import annotations

PNW_BOARDS: dict[str, list[str]] = {
    "greenhouse": [
        # aerospace / defense / hardware
        "spacex", "andurilindustries", "carbonrobotics", "axon",
        # Seattle / Bellevue tech
        "smartsheet", "offerup", "truveta", "usafacts", "qualtrics", "samsara", "brex",
        "solutions",  # Cadence Solutions
        # games
        "bungie",
        # remote-friendly employers already producing good matches
        "gitlab", "coinbase", "wikimedia", "freestonecapitalmanagement",
    ],
    "lever": ["outreach", "rover", "shieldai", "researchinnovations.com", "pditechnologies"],
    "ashby": ["qumulo", "spruceid", "sardine", "amplify", "GovSignals", "whatnot", "nooks", "1password"],
}


def boards_for(source: str, cfg: dict) -> list[str]:
    """The configured companies plus the built-in PNW boards for `source`, without duplicates, in order."""
    companies = list(cfg.get("companies") or [])
    if cfg.get("pnw_boards", True):
        companies += PNW_BOARDS.get(source, [])
    seen: set[str] = set()
    out: list[str] = []
    for c in companies:
        key = str(c).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(str(c).strip())
    return out
