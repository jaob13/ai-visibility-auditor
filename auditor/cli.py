"""
cli.py - the command you run. Wires the five stages together in order.

Examples:

  # Offline demo with the bundled sample answers (no API keys, costs nothing):
  python -m auditor examples/greenprint.json --replay examples/sample_answers.json

  # Live audit: ask Claude, label stances with Claude, cache answers in runs/cache:
  set ANTHROPIC_API_KEY=sk-...
  python -m auditor examples/greenprint.json --engines claude --label

  # Re-score an earlier live run for free (answers come from the cache):
  python -m auditor examples/greenprint.json --engines claude

Steps performed:
  1. load the audit config                       (config.py)
  2. collect one answer per engine per question  (engines.py, cached)
  3. extract structured facts from each answer   (extract.py, guard included)
  4. score every brand                           (score.py)
  5. write report.html, scores.csv, results.json (report.py)
"""

from __future__ import annotations

import argparse
import sys

from .config import load_config
from .engines import ClaudeEngine, collect_answers, load_replay_engines, make_engine
from .extract import extract
from .report import write_reports
from .score import score_audit


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="auditor", description="Measure how AI assistants recommend a brand.")
    p.add_argument("config", help="audit JSON file (see examples/greenprint.json)")
    p.add_argument("--engines", help="comma list overriding the config, e.g. claude,openai,gemini")
    p.add_argument("--replay", help="saved-answers JSON to use instead of calling live APIs")
    p.add_argument("--label", action="store_true", help="use Claude to label stance (needs ANTHROPIC_API_KEY)")
    p.add_argument("--out", default="runs/latest", help="output folder (default runs/latest)")
    p.add_argument("--cache", default="runs/cache", help="answer cache folder (default runs/cache)")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    print(f"Auditing {cfg.target.name} against {len(cfg.competitors)} competitors, "
          f"{len(cfg.questions)} questions.")

    # Stage 2: ask
    if args.replay:
        engines = load_replay_engines(args.replay)
        cache = None                      # replayed answers are already saved; don't cache them
    else:
        names = args.engines.split(",") if args.engines else cfg.engines
        engines = [make_engine(n.strip()) for n in names]
        cache = args.cache
    answers = collect_answers(engines, cfg.questions, cache_dir=cache)

    # Stage 3: translate (rules always; AI labeling only with --label)
    labeler = ClaudeEngine() if args.label else None
    rows = [(a, extract(a.text, cfg.brands, labeler)) for a in answers]

    # Stages 4 and 5: judge and show
    result = score_audit(cfg, rows)
    report = write_reports(cfg, result, args.out, sample=bool(args.replay))

    target = next(b for b in result.brands if b.is_target)
    print(f"\n{cfg.target.name}: visibility score {target.score}/100, named in "
          f"{target.mention_rate:.0%} of answers, {len(result.gaps)} gap(s).")
    print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
