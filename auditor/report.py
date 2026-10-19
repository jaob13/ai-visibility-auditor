"""
report.py - SHOW the results.

Writes three files into the output folder:
  report.html   a single self-contained page (no internet needed to open it)
  scores.csv    one row per brand, for Google Sheets or Excel
  results.json  everything, including every answer and what was extracted from it

The HTML report reads top to bottom the way a client would ask:
  1. How visible are we?                (the target's score, per engine)
  2. How do we compare?                 (leaderboard of every tracked brand)
  3. Where are we losing?               (gaps: questions where competitors were named and we were not)
  4. Who else is the AI recommending?   (untracked products it named)
  5. Show me the evidence.              (every raw answer, with what was extracted)
"""

from __future__ import annotations

import csv
import html
import io
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .config import AuditConfig
from .score import WEIGHTS, AuditResult

CSS = """
:root{--ink:#16202e;--muted:#5b6675;--line:#e3e7ec;--bg:#f7f8fa;--card:#fff;--accent:#1f6feb;--target:#0f9d58;--warn:#b54708}
@media (prefers-color-scheme:dark){:root{--ink:#e7ebf0;--muted:#9aa5b1;--line:#2b3440;--bg:#11161c;--card:#171d24;--accent:#58a6ff;--target:#3fb950;--warn:#f0883e}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink);background:var(--bg)}
main{max-width:960px;margin:0 auto;padding:32px 16px 64px}h1{margin:0 0 4px;font-size:26px}h2{margin:36px 0 12px;font-size:18px}
.muted{color:var(--muted)}.banner{background:var(--warn);color:#fff;padding:10px 14px;border-radius:8px;margin:16px 0;font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}.big{font-size:34px;font-weight:700}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
td.num{text-align:right;font-variant-numeric:tabular-nums}tr.target td{font-weight:600}tr.target td:first-child{border-left:4px solid var(--target)}
.bar{height:8px;background:var(--line);border-radius:4px;min-width:80px}.bar>span{display:block;height:100%;background:var(--accent);border-radius:4px}
tr.target .bar>span{background:var(--target)}details{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:8px 0;padding:8px 12px}
summary{cursor:pointer}pre{white-space:pre-wrap;font:13px/1.45 ui-monospace,Consolas,monospace;margin:8px 0}.wrap{overflow-x:auto}
"""


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _e(s) -> str:
    return html.escape(str(s))


def render_html(cfg: AuditConfig, res: AuditResult, sample: bool) -> str:
    target = next(b for b in res.brands if b.is_target)
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>AI Visibility: {_e(cfg.target.name)}</title><style>{CSS}</style></head><body><main>",
             f"<h1>AI visibility audit: {_e(cfg.target.name)}</h1>",
             f"<div class='muted'>{date.today():%B %d, %Y} &middot; {len(cfg.questions)} questions &middot; "
             f"engines: {_e(', '.join(res.target_by_engine))} &middot; {len(res.rows)} answers</div>"]
    if sample:
        parts.append("<div class='banner'>Sample data: these answers are illustrative examples bundled "
                     "with the tool, not live AI responses. Run with API keys for a real audit.</div>")

    # 1. headline
    parts.append("<div class='cards'>")
    parts.append(f"<div class='card'><div class='muted'>Visibility score</div><div class='big'>{target.score}</div>"
                 f"<div class='muted'>out of 100</div></div>")
    parts.append(f"<div class='card'><div class='muted'>Named in</div><div class='big'>{_pct(target.mention_rate)}</div>"
                 f"<div class='muted'>of answers</div></div>")
    for eng, sc in res.target_by_engine.items():
        parts.append(f"<div class='card'><div class='muted'>{_e(eng)}</div><div class='big'>{sc}</div>"
                     f"<div class='muted'>score</div></div>")
    parts.append("</div>")

    # 2. leaderboard
    stance_cols = "<th>Recommended</th><th>Negative</th>" if res.labeled else ""
    parts.append("<h2>How you compare</h2><div class='wrap'><table><tr><th>Brand</th><th>Score</th><th></th>"
                 f"<th>Named</th><th>Top 3</th><th>Named first</th><th>Avg rank</th><th>Site cited</th>{stance_cols}</tr>")
    for b in res.brands:
        stance = (f"<td class='num'>{b.recommended}</td><td class='num'>{b.negative}</td>" if res.labeled else "")
        parts.append(
            f"<tr class='{'target' if b.is_target else ''}'><td>{_e(b.brand)}</td><td class='num'>{b.score}</td>"
            f"<td><div class='bar'><span style='width:{b.score}%'></span></div></td>"
            f"<td class='num'>{_pct(b.mention_rate)}</td><td class='num'>{_pct(b.top3_rate)}</td>"
            f"<td class='num'>{_pct(b.first_rate)}</td><td class='num'>{b.avg_rank if b.avg_rank else '&ndash;'}</td>"
            f"<td class='num'>{_pct(b.citation_rate)}</td>{stance}</tr>")
    parts.append("</table></div>")
    w = ", ".join(f"{k.replace('_', ' ')} {int(v * 100)}%" for k, v in WEIGHTS.items())
    parts.append(f"<p class='muted'>Score weights: {w}. Rank 1 means named first.</p>")

    # 3. gaps
    n = len(res.gaps)
    parts.append(f"<h2>Where you're missing ({n} answer{'' if n == 1 else 's'})</h2>")
    if res.gaps:
        parts.append("<div class='wrap'><table><tr><th>Engine</th><th>Question</th><th>Named instead</th></tr>")
        for g in res.gaps:
            parts.append(f"<tr><td>{_e(g.engine)}</td><td>{_e(g.question)}</td><td>{_e(', '.join(g.competitors_named))}</td></tr>")
        parts.append("</table></div>")
    else:
        parts.append("<p>None. Every answer that named a tracked competitor also named you.</p>")

    # 4. discovered
    if res.discovered:
        parts.append("<h2>Other products the AI recommended</h2><p class='muted'>Not in your tracked list. "
                     "Consider adding the frequent ones as competitors.</p><ul>")
        parts += [f"<li>{_e(name)} &times;{n}</li>" for name, n in res.discovered[:15]]
        parts.append("</ul>")

    # 5. evidence
    method = ("Brand mentions, order and citations were found by text matching. Stance labels came from Claude, "
              f"checked against the text; {res.rejected_claims} unverifiable claim(s) were discarded."
              if res.labeled else "Brand mentions, order and citations were found by text matching (no AI labeling).")
    parts.append(f"<h2>Evidence</h2><p class='muted'>{method}</p>")
    for a, ex in res.rows:
        found = ", ".join(f"{i}. {n} ({ex.stance.get(n, 'neutral')})" for i, n in enumerate(ex.ranked, 1)) or "no tracked brands"
        parts.append(f"<details><summary><b>{_e(a.engine)}</b> &middot; {_e(a.question)}</summary>"
                     f"<p class='muted'>Found: {_e(found)}</p><pre>{_e(a.text)}</pre></details>")

    parts.append("</main></body></html>")
    return "".join(parts)


def build_payload(cfg: AuditConfig, res: AuditResult, sample: bool = False) -> dict:
    """Everything about a run as plain data: used for results.json and the web app."""
    return {
        "target": cfg.target.name, "sample_data": sample,
        "competitors": [b.name for b in cfg.competitors], "questions": cfg.questions,
        "brands": [asdict(b) for b in res.brands],
        "target_by_engine": res.target_by_engine,
        "gaps": [asdict(g) for g in res.gaps],
        "discovered": res.discovered,
        "rejected_claims": res.rejected_claims,
        "answers": [{"engine": a.engine, "question": a.question, "text": a.text,
                     "ranked": ex.ranked, "stance": ex.stance, "cited": sorted(ex.cited),
                     "others": ex.others, "rejected": ex.rejected, "method": ex.method, "note": ex.note}
                    for a, ex in res.rows],
    }


CSV_FIELDS = ["brand", "is_target", "score", "mention_rate", "top3_rate", "first_rate",
              "avg_rank", "citation_rate", "share_of_voice", "recommended", "negative", "answers"]


def render_csv(res: AuditResult) -> str:
    """Leaderboard as CSV text (one row per brand) for Sheets or Excel."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    for b in res.brands:
        w.writerow(asdict(b))
    return buf.getvalue()


def write_reports(cfg: AuditConfig, res: AuditResult, out_dir: str | Path, sample: bool = False) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(render_html(cfg, res, sample), encoding="utf-8")
    (out / "scores.csv").write_text(render_csv(res), encoding="utf-8", newline="")
    (out / "results.json").write_text(json.dumps(build_payload(cfg, res, sample), indent=2), encoding="utf-8")
    return out / "report.html"
