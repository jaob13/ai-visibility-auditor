"""
pipeline.py - one function that runs a whole audit: ASK -> TRANSLATE -> JUDGE.

Both the web app and the command line call `run_audit`, so they can never drift
apart. It takes an approved AuditConfig plus the engines to ask, and returns the
scored result. Reporting/exporting is left to the caller.
"""

from __future__ import annotations

from .config import AuditConfig
from .engines import collect_answers
from .extract import extract
from .score import AuditResult, score_audit


def run_audit(cfg: AuditConfig, engines, labeler=None, cache_dir=None, log=print) -> AuditResult:
    log(f"Asking {len(engines)} AI engine(s) {len(cfg.questions)} questions each...")
    answers = collect_answers(engines, cfg.questions, cache_dir=cache_dir, log=log)
    log("Reading the answers" + (" (with Claude tone labels)..." if labeler else "..."))
    rows = []
    for i, a in enumerate(answers, 1):
        rows.append((a, extract(a.text, cfg.brands, labeler)))
        if labeler:
            log(f"  labeled {i}/{len(answers)}")
    log("Scoring...")
    return score_audit(cfg, rows)
