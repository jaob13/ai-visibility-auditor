# AI Visibility Auditor

When a small business owner asks ChatGPT, Claude, or Gemini *"what software should I use?"*, which brands get recommended, and in what order? This tool measures that.

You give it a brand, its competitors, and the questions real buyers ask. It asks each AI engine each question, finds which brands were named and how prominently, and produces a 0–100 **visibility score** for every brand plus a list of **gaps**: questions where competitors were recommended and you were not.

Designed and directed by Jonathan Bridges ([jonathanbridges.dev](https://jonathanbridges.dev)), built AI-assisted with Claude.

## How it works

```
config.json ──> ASK ──────> TRANSLATE ─────────> JUDGE ──────────> SHOW
                engines.py  extract.py            score.py          report.py
                Claude      rules: names, order,  fixed-weight      report.html
                OpenAI      citations             0–100 score,      scores.csv
                Gemini      AI: stance labels     gaps, per-engine  results.json
                (cached)    GUARD: AI claims must
                            match the text
```

**The model translates, the scripts judge.** AI is used to read answers and label tone (recommended / neutral / negative). It never decides a score. Every number comes from plain Python that gives the same result every run, and canary tests pin those numbers down.

**AI that checks AI.** The AI labeler can only describe brands that text matching actually found in the answer. If it claims a brand appeared and the text doesn't contain it, the claim is discarded and counted in the report.

## Quick start

Requires Python 3.10+. No packages to install for the tool itself (standard library only).

```bash
# Offline demo with bundled sample answers (no keys, free):
python -m auditor examples/greenprint.json --replay examples/sample_answers.json
# open runs/latest/report.html

# Live audit with Claude, plus Claude stance labeling:
export ANTHROPIC_API_KEY="sk-ant-..."           # Windows PowerShell: $env:ANTHROPIC_API_KEY = "sk-ant-..."
python -m auditor examples/greenprint.json --engines claude --label

# All three engines (needs OPENAI_API_KEY and GEMINI_API_KEY too):
python -m auditor examples/greenprint.json --engines claude,openai,gemini --label
```

Live answers are cached in `runs/cache/`, so re-running the same audit re-scores for free.

Run the tests: `pip install pytest` then `python -m pytest -q`.

## Scoring

| Metric | Weight | Meaning |
|---|---|---|
| Mention rate | 35% | Share of answers that name the brand |
| Top-3 rate | 25% | Share of answers where it's among the first three brands named |
| First rate | 20% | Share of answers where it's named first |
| Citation rate | 10% | Share of answers that reference the brand's website |
| Share of voice | 10% | Its mentions ÷ all tracked-brand mentions |

Weights live in one place (`auditor/score.py`). Stance counts are reported beside the score, not inside it, so labeled and unlabeled runs score identically.

## Project layout

```
auditor/config.py    load + validate the audit file
auditor/engines.py   Claude / OpenAI / Gemini / replay engines, retries, cache
auditor/extract.py   rules extraction, AI stance labeling, the guard
auditor/score.py     metrics, weights, gaps, per-engine scores
auditor/report.py    HTML / CSV / JSON output
auditor/cli.py       the command that runs all five stages
examples/            sample audit config + illustrative sample answers
tests/               canary tests (no network)
docs/HOW_IT_WORKS.md plain-English walkthrough
```

## Limitations (stated plainly)

- It queries the raw model APIs. Consumer apps may add live web search, so a buyer's screen can differ.
- AI answers vary run to run. More questions and repeated runs give steadier numbers; the cache makes any single run reproducible.
- A brand named *in the question* (e.g. "alternatives to Jobber") often gets echoed in the answer and counted as a mention. Read gaps and ranks for those questions with that in mind.
- The bundled sample answers are hand-written illustrations, not real AI output.
