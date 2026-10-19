"""
AI Visibility Auditor
=====================

Measures how often, and how prominently, AI assistants (Claude, ChatGPT, Gemini)
recommend a brand when people ask them buying questions.

The pipeline has five stages, one module each:

    config.py   -> what to audit: the brand, its competitors, the buyer questions
    engines.py  -> ASK:       send each question to each AI engine, get raw answers
    extract.py  -> TRANSLATE: turn each free-text answer into structured facts
    score.py    -> JUDGE:     compute deterministic, repeatable scores from those facts
    report.py   -> SHOW:      write an HTML report plus CSV/JSON for spreadsheets

Design rule used everywhere: "the model translates, the scripts judge."
An AI model is allowed to read messy text and summarize it into structure.
It is never allowed to decide a score. Every number in the report comes from
plain Python arithmetic that gives the same answer every time it runs.
"""

__version__ = "0.1.0"
