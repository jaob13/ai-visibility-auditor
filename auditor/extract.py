"""
extract.py - TRANSLATE a free-text AI answer into structured facts.

For every answer we want to know:
  1. Which tracked brands appear, and in what order (rank 1 = named first).
  2. Whether each brand was actually recommended, just mentioned, or warned against.
  3. Whether the answer cites a brand's own website.
  4. Which OTHER products the AI named that we are not tracking yet
     (useful for discovering competitors you forgot).

Two layers, on purpose:

  RULES layer (always runs, no AI): plain text matching. It finds brand names and
  website domains, and ranks brands by where they first appear. Same input always
  gives the same output.

  AI layer (optional, uses Claude): reads the answer the way a person would and
  labels each brand's stance ("recommended", "neutral", "negative") and lists
  untracked products. Text matching cannot tell "Jobber is great" from
  "avoid Jobber", which is why this layer exists.

The GUARD between them ("AI that checks AI"): the AI layer may only label brands
that the rules layer actually found in the text. If Claude claims a brand was
mentioned and the text does not contain it, that claim is thrown out and logged
in `rejected`. The model can describe the answer; it cannot invent facts about it.
Rank always comes from the rules layer, never from the model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .config import Brand

STANCES = ("recommended", "neutral", "negative")


@dataclass
class Extraction:
    """Structured facts pulled from one answer."""

    ranked: list[str]                      # tracked brands in order of first appearance
    stance: dict[str, str]                 # brand -> recommended | neutral | negative
    cited: set[str]                        # brands whose website appears in the answer
    others: list[str] = field(default_factory=list)    # untracked products the AI named
    rejected: list[str] = field(default_factory=list)  # AI claims the guard threw out
    method: str = "rules"                  # "rules" or "rules+ai"
    note: str = ""                         # why the AI layer was skipped, if it was

    def rank_of(self, brand: str) -> int | None:
        """1-based position, or None if the brand was not mentioned."""
        return self.ranked.index(brand) + 1 if brand in self.ranked else None


# ---------------------------------------------------------------- rules layer

def _name_pattern(name: str) -> re.Pattern:
    """Match a brand name as a whole word, case-insensitive, tolerant of extra
    spaces. 'Jobber' matches 'jobber' but not 'Jobbers'."""
    parts = [re.escape(p) for p in name.split()]
    return re.compile(r"(?<![\w-])" + r"\s+".join(parts) + r"(?![\w-])", re.IGNORECASE)


def find_mentions(text: str, brands: list[Brand]) -> list[str]:
    """Return tracked brand names ordered by where each first appears in the text."""
    first_seen: dict[str, int] = {}
    for b in brands:
        positions = [m.start() for n in b.names for m in _name_pattern(n).finditer(text)]
        positions += [text.lower().find(d) for d in b.domains if d in text.lower()]
        if positions:
            first_seen[b.name] = min(positions)
    return sorted(first_seen, key=first_seen.get)


def find_citations(text: str, brands: list[Brand]) -> set[str]:
    """Brands whose own website domain appears in the answer."""
    low = text.lower()
    return {b.name for b in brands if any(d in low for d in b.domains)}


def extract_rules(text: str, brands: list[Brand]) -> Extraction:
    ranked = find_mentions(text, brands)
    return Extraction(ranked=ranked, stance={b: "neutral" for b in ranked},
                      cited=find_citations(text, brands), method="rules")


# ------------------------------------------------------------------- AI layer

EXTRACT_SYSTEM_PROMPT = """You label product mentions in an AI assistant's answer.
Return ONLY a JSON object, no prose, shaped exactly like:
{"stances": {"<tracked brand>": "recommended" | "neutral" | "negative"},
 "other_products": ["<product name>", ...]}
Rules:
- "stances" may only use names from the tracked list, and only brands the answer actually names.
- recommended = presented as a good choice; negative = discouraged or criticized; neutral = mentioned without a verdict.
- other_products = software products the answer names that are NOT on the tracked list."""


def _parse_json_object(raw: str) -> dict:
    """Pull the first {...} block out of a model reply. Models sometimes wrap JSON
    in code fences or add a sentence; this tolerates that and fails clearly otherwise."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"No JSON object in model reply: {raw[:120]!r}")
    return json.loads(raw[start:end + 1])


def apply_guard(rules: Extraction, ai: dict) -> Extraction:
    """Merge the AI's labels into the rules result, keeping only verifiable claims."""
    stance = dict(rules.stance)
    rejected: list[str] = []
    for brand, label in (ai.get("stances") or {}).items():
        if brand not in rules.ranked:
            rejected.append(brand)            # AI says it's there; the text says no
        elif label in STANCES:
            stance[brand] = label
    tracked_lower = {b.lower() for b in rules.ranked}
    others = sorted({o.strip() for o in (ai.get("other_products") or [])
                     if o.strip() and o.strip().lower() not in tracked_lower})
    return Extraction(ranked=rules.ranked, stance=stance, cited=rules.cited,
                      others=others, rejected=rejected, method="rules+ai")


def extract(text: str, brands: list[Brand], labeler=None) -> Extraction:
    """Run the rules layer, then (if a labeler engine is given) the AI layer + guard.
    If the AI call or its JSON fails, fall back to the rules result instead of
    crashing the whole audit; the method field records which one was used."""
    rules = extract_rules(text, brands)
    if labeler is None:
        return rules
    tracked = ", ".join(b.name for b in brands)
    prompt = f"Tracked brands: {tracked}\n\nAnswer to label:\n\"\"\"\n{text}\n\"\"\""
    try:
        raw = labeler.ask(prompt, system=EXTRACT_SYSTEM_PROMPT, max_tokens=500)
        return apply_guard(rules, _parse_json_object(raw))
    except Exception as e:  # noqa: BLE001 - any labeling failure degrades to rules
        rules.note = f"AI labeling failed, used rules only: {e}"
        return rules
