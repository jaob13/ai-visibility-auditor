"""
config.py - WHAT we are auditing.

An audit is described by one JSON file (see examples/greenprint.json):

    {
      "target": {"name": "GreenPrint", "aliases": ["Green Print"], "domains": ["getgreenprint.app"]},
      "competitors": [{"name": "Jobber", "aliases": [], "domains": ["getjobber.com"]}, ...],
      "questions": ["What is the best software for a small cleaning company?", ...],
      "engines": ["claude", "openai", "gemini"]
    }

- "target" is the brand we care about.
- "competitors" are the brands we compare it against.
- "aliases" are other spellings people (and AIs) use, so "Housecall Pro" and
  "HousecallPro" count as the same brand.
- "domains" are the brand's websites, used to detect when an AI cites the brand's site.

This module only loads and validates that file. It does no network calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Brand:
    """One brand we track. `names` is the official name plus every alias."""

    name: str
    aliases: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    is_target: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass
class AuditConfig:
    """Everything needed to run one audit."""

    target: Brand
    competitors: list[Brand]
    questions: list[str]
    engines: list[str] = field(default_factory=lambda: ["claude"])

    @property
    def brands(self) -> list[Brand]:
        """Target first, then competitors. Order matters only for display."""
        return [self.target, *self.competitors]


def _brand(raw: dict, is_target: bool) -> Brand:
    if not raw.get("name"):
        raise ValueError(f"Every brand needs a 'name': {raw!r}")
    return Brand(
        name=raw["name"].strip(),
        aliases=tuple(a.strip() for a in raw.get("aliases", []) if a.strip()),
        domains=tuple(d.strip().lower() for d in raw.get("domains", []) if d.strip()),
        is_target=is_target,
    )


def load_config(path: str | Path) -> AuditConfig:
    """Read and validate an audit file. Fails loudly on anything missing,
    because a silently wrong config produces a confidently wrong report."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    if "target" not in raw:
        raise ValueError("Config needs a 'target' brand.")
    questions = [q.strip() for q in raw.get("questions", []) if q.strip()]
    if not questions:
        raise ValueError("Config needs at least one question.")

    cfg = AuditConfig(
        target=_brand(raw["target"], is_target=True),
        competitors=[_brand(c, is_target=False) for c in raw.get("competitors", [])],
        questions=questions,
        engines=raw.get("engines", ["claude"]),
    )

    # Two brands sharing a name or alias would make mentions ambiguous.
    seen: dict[str, str] = {}
    for b in cfg.brands:
        for n in b.names:
            key = n.lower()
            if key in seen and seen[key] != b.name:
                raise ValueError(f"'{n}' is used by both {seen[key]} and {b.name}.")
            seen[key] = b.name
    return cfg
