# AI Visibility Auditor

When someone asks ChatGPT, Claude, or Gemini *"what's the best day spa near me?"* or *"what software should my cleaning company use?"*, does your business get recommended? This app measures it.

Type in a business, its website, a few answers about it, and how far its market reaches. The app reads the website, figures out who it competes with, writes the questions real customers ask, asks the AI assistants, and scores every business 0–100. It also lists the **gaps**: questions where a competitor got recommended and you didn't. Export everything as a report, PDF, CSV, or JSON.

Designed and directed by Jonathan Bridges ([jonathanbridges.dev](https://jonathanbridges.dev)), built AI-assisted with Claude.

## Run it

Requires Python 3.10+. Nothing to install (standard library only).

```bash
git clone https://github.com/jaob13/ai-visibility-auditor
cd ai-visibility-auditor
python -m auditor
```

Your browser opens to `http://127.0.0.1:8765`. Click **see a sample report** to try it with no key, or fill in a business and paste your Anthropic API key under *AI settings*.

Keys are typed into the page, held in memory for that request only, and never written to disk. The app only listens on your own computer.

## How it works

```
 1. YOU TYPE            2. PLAN (discover.py)             3. REVIEW       4. AUDIT                     5. EXPORT
 name, website,   ──>   read the website              ──>  edit the  ──>  ask each AI each question ──> HTML report
 what you do,           Google Places: real nearby        AI's plan       find brands, order, links     Print / PDF
 customers,             competitors in your radius        in the app      Claude labels tone            CSV scores
 location + reach       Claude: competitors + questions                   GUARD checks the AI           JSON (all data)
                        GUARD cleans the plan                             fixed-weight 0–100 score
```

**The AI proposes, the person approves.** Claude drafts the competitor list and questions from what you entered and what your website says. You review and edit before anything runs.

**The model translates, the scripts judge.** AI reads answers and labels tone. It never decides a score. Every number comes from plain Python that gives the same result every run.

**AI that checks AI.** Two guards keep the AI honest. At planning time, code drops your own business from the competitor list, removes duplicates, and throws out any question that names a brand. At scoring time, Claude can only label brands that text matching actually found in the answer.

### Market reach

| Setting | Competitors come from | Questions mention |
|---|---|---|
| **Local radius** (1–100 mi) | Google Places (real map data, filtered by actual distance) if you add a Places key, plus Claude | your city |
| **My state** | Claude, scoped to your state | your state/region |
| **Nationwide** | Claude, national players | no location |

## Scoring

| Metric | Weight | Meaning |
|---|---|---|
| Mention rate | 35% | Share of answers that name the business |
| Top-3 rate | 25% | Share of answers where it's among the first three named |
| First rate | 20% | Share of answers where it's named first |
| Citation rate | 10% | Share of answers that reference its website |
| Share of voice | 10% | Its mentions ÷ all tracked-business mentions |

Weights live in one place (`auditor/score.py`). Canary tests pin known scores so the math can't drift silently.

## Project layout

```
auditor/web/index.html  the interface (form → review → progress → results/export)
auditor/server.py       local web server, background jobs, export downloads
auditor/discover.py     website reading, Google Places, Claude planning, plan guard
auditor/pipeline.py     run_audit(): ask → translate → judge (shared by app and CLI)
auditor/engines.py      Claude / OpenAI / Gemini / replay engines, retries, cache
auditor/extract.py      text matching, Claude tone labels, the answer guard
auditor/score.py        metrics, weights, gaps, per-engine scores
auditor/report.py       HTML / CSV / JSON output
auditor/cli.py          command-line entry point
docs/HOW_IT_WORKS.md    plain-English walkthrough
tests/                  22 offline tests (no network, fake AI engines)
```

Tests: `pip install pytest` then `python -m pytest -q`.

Command-line mode still works for scripted runs: `python -m auditor examples/greenprint.json --replay examples/sample_answers.json`.

## Limitations (stated plainly)

- It asks the AI models' APIs directly. Consumer apps may add live web search, so a customer's screen can differ.
- Without a Places key, competitors come from the AI's knowledge and can be outdated. The review step exists for this reason.
- Small local businesses are often unknown to AI models. A score of 0 is a real finding, not a bug.
- AI answers vary between runs. More questions give steadier numbers, and the answer cache makes any run reproducible.
- The bundled sample report uses hand-written illustrative answers, not real AI output.
