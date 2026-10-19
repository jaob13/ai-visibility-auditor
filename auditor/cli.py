"""
cli.py - the command you run. Wires the five stages together in order.

Examples:

  # The web app (recommended): opens http://127.0.0.1:8765 in your browser
  python -m auditor

  # Offline demo with the bundled sample answers (no API keys, costs nothing):
  python -m auditor examples/greenprint.json --replay examples/sample_answers.json

  # Live audit: ask Claude, label stances with Claude, cache answers in runs/cache:
  $env:ANTHROPIC_API_KEY = "sk-ant-..."   (PowerShell)
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
from .engines import ClaudeEngine, load_replay_engines, make_engine
from .pipeline import run_audit
from .report import write_reports


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] == "serve" or argv[0].startswith("--port") or argv[0] == "--no-browser":
        sp = argparse.ArgumentParser(prog="auditor", description="Start the web app.")
        sp.add_argument("--port", type=int, default=8765)
        sp.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
        a = sp.parse_args(argv[1:] if argv and argv[0] == "serve" else argv)
        from .server import serve
        serve(a.port, open_browser=not a.no_browser)
        return 0

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
    # Stages 3 and 4: translate (AI tone labels only with --label) and judge
    labeler = ClaudeEngine() if args.label else None
    result = run_audit(cfg, engines, labeler=labeler, cache_dir=cache)

    # Stage 5: show
    report = write_reports(cfg, result, args.out, sample=bool(args.replay))

    target = next(b for b in result.brands if b.is_target)
    print(f"\n{cfg.target.name}: visibility score {target.score}/100, named in "
          f"{target.mention_rate:.0%} of answers, {len(result.gaps)} gap(s).")
    print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
