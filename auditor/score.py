"""
score.py - JUDGE. Turns extracted facts into numbers. No AI anywhere in here.

For each brand, across every (engine, question) answer:

  mention_rate    share of answers that name the brand at all
  top3_rate       share of answers where it is among the first three brands named
  first_rate      share of answers where it is named first
  citation_rate   share of answers that point to the brand's own website
  share_of_voice  the brand's mentions divided by all tracked-brand mentions
  avg_rank        average position when it IS mentioned (1 = first). Lower is better.

Those combine into one 0-100 VISIBILITY SCORE using fixed weights (WEIGHTS below).
Changing a weight is a deliberate, visible decision in one place, and the canary
tests in tests/ fail if the scoring math drifts.

The score uses only rules-layer facts (mentions, order, citations), so a run with
the AI labeler and a run without it produce the same score. Stance (recommended /
negative) is reported next to the score as extra context, never inside it.

Also produced:
  per-engine scores for the target brand ("Claude knows us, Gemini doesn't")
  GAPS: questions where the target was absent but a competitor was named.
        These are the content opportunities, the most actionable part of the report.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .config import AuditConfig
from .engines import Answer
from .extract import Extraction

WEIGHTS = {
    "mention_rate": 0.35,
    "top3_rate": 0.25,
    "first_rate": 0.20,
    "citation_rate": 0.10,
    "share_of_voice": 0.10,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "weights must sum to 1"


@dataclass
class BrandScore:
    brand: str
    is_target: bool
    answers: int
    mention_rate: float
    top3_rate: float
    first_rate: float
    citation_rate: float
    share_of_voice: float
    avg_rank: float | None
    recommended: int          # answers where the AI layer labeled it recommended
    negative: int             # answers where the AI layer labeled it negative
    score: float


@dataclass
class Gap:
    engine: str
    question: str
    competitors_named: list[str]


@dataclass
class AuditResult:
    brands: list[BrandScore]
    target_by_engine: dict[str, float]
    gaps: list[Gap]
    discovered: list[tuple[str, int]]          # untracked products and how often they appeared
    rejected_claims: int                        # AI claims the guard threw out
    labeled: bool                               # whether the AI stance layer ran
    rows: list[tuple[Answer, Extraction]] = field(default_factory=list)


def visibility_score(metrics: dict[str, float]) -> float:
    """Weighted sum of the five rates, scaled to 0-100 and rounded to one decimal."""
    return round(100 * sum(WEIGHTS[k] * metrics[k] for k in WEIGHTS), 1)


def score_brand(brand: str, is_target: bool, rows: list[tuple[Answer, Extraction]]) -> BrandScore:
    n = len(rows)
    ranks = [ex.rank_of(brand) for _, ex in rows]
    mentioned = [r for r in ranks if r is not None]
    total_mentions = sum(len(ex.ranked) for _, ex in rows)

    metrics = {
        "mention_rate": len(mentioned) / n if n else 0.0,
        "top3_rate": sum(1 for r in mentioned if r <= 3) / n if n else 0.0,
        "first_rate": sum(1 for r in mentioned if r == 1) / n if n else 0.0,
        "citation_rate": sum(1 for _, ex in rows if brand in ex.cited) / n if n else 0.0,
        "share_of_voice": len(mentioned) / total_mentions if total_mentions else 0.0,
    }
    return BrandScore(
        brand=brand, is_target=is_target, answers=n,
        avg_rank=round(sum(mentioned) / len(mentioned), 2) if mentioned else None,
        recommended=sum(1 for _, ex in rows if ex.stance.get(brand) == "recommended"),
        negative=sum(1 for _, ex in rows if ex.stance.get(brand) == "negative"),
        score=visibility_score(metrics),
        **{k: round(v, 4) for k, v in metrics.items()},
    )


def score_audit(cfg: AuditConfig, rows: list[tuple[Answer, Extraction]]) -> AuditResult:
    brands = sorted((score_brand(b.name, b.is_target, rows) for b in cfg.brands),
                    key=lambda s: (-s.score, s.brand))

    engines = sorted({a.engine for a, _ in rows})
    target_by_engine = {
        e: score_brand(cfg.target.name, True, [r for r in rows if r[0].engine == e]).score
        for e in engines
    }

    gaps = [Gap(a.engine, a.question, ex.ranked)
            for a, ex in rows if cfg.target.name not in ex.ranked and ex.ranked]

    others = Counter(o for _, ex in rows for o in ex.others)
    return AuditResult(
        brands=brands, target_by_engine=target_by_engine, gaps=gaps,
        discovered=others.most_common(),
        rejected_claims=sum(len(ex.rejected) for _, ex in rows),
        labeled=any(ex.method == "rules+ai" for _, ex in rows),
        rows=rows,
    )
