"""
engines.py - ASK each AI engine each question.

An "engine" is anything that takes a question and returns an answer as text.
Every engine follows the same tiny interface (`ask(question) -> str`), so the
rest of the pipeline never cares which AI it is talking to. Adding a new AI
means adding one small class here and nothing else.

Engines included:
- ClaudeEngine   Anthropic's Messages API      (needs ANTHROPIC_API_KEY)
- OpenAIEngine   OpenAI's Chat Completions API (needs OPENAI_API_KEY)
- GeminiEngine   Google's Gemini API           (needs GEMINI_API_KEY)
- ReplayEngine   reads saved answers from disk instead of calling an API.
                 Used for the offline demo, for tests, and to re-score an old
                 run without paying for API calls again.

Every live answer is saved to a cache file. Re-running the same audit reuses
those answers, so results are reproducible and you only pay once.

Uses only the Python standard library (urllib), so there is nothing to install.

Honest limitation: these are the raw model APIs. The consumer apps (ChatGPT,
Gemini, Claude.ai) may add live web search, so what a real buyer sees can differ.
The audit measures what the models themselves recommend.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# The instruction every engine gets. Kept neutral on purpose: we want the AI's
# normal recommendation, not one we nudged toward or away from any brand.
ASK_SYSTEM_PROMPT = (
    "You are a helpful assistant answering a small business owner's question. "
    "Give a direct, practical answer and name specific products where relevant."
)


@dataclass
class Answer:
    """One AI's answer to one question."""

    engine: str
    question: str
    text: str


def _post_json(url: str, payload: dict, headers: dict, retries: int = 3) -> dict:
    """POST JSON and return parsed JSON. Retries on rate limits (429) and server
    errors (5xx) with growing waits; any other error is raised immediately."""
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers={"content-type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"{url} returned HTTP {e.code}: {detail}") from e
    raise RuntimeError(f"{url} failed after {retries} attempts")


def _require_key(var: str) -> str:
    key = os.environ.get(var)
    if not key:
        raise RuntimeError(f"Set the {var} environment variable to use this engine.")
    return key


class ClaudeEngine:
    name = "claude"

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model

    def ask(self, question: str, system: str = ASK_SYSTEM_PROMPT, max_tokens: int = 1200) -> str:
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            {"model": self.model, "max_tokens": max_tokens, "system": system,
             "messages": [{"role": "user", "content": question}]},
            {"x-api-key": _require_key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"},
        )
        return "".join(block.get("text", "") for block in data.get("content", []))


class OpenAIEngine:
    name = "openai"

    def __init__(self, model: str = "gpt-4o-mini"):
        self.model = model

    def ask(self, question: str) -> str:
        data = _post_json(
            "https://api.openai.com/v1/chat/completions",
            {"model": self.model, "messages": [
                {"role": "system", "content": ASK_SYSTEM_PROMPT},
                {"role": "user", "content": question}]},
            {"authorization": f"Bearer {_require_key('OPENAI_API_KEY')}"},
        )
        return data["choices"][0]["message"]["content"]


class GeminiEngine:
    name = "gemini"

    def __init__(self, model: str = "gemini-2.0-flash"):
        self.model = model

    def ask(self, question: str) -> str:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}"
               f":generateContent?key={_require_key('GEMINI_API_KEY')}")
        data = _post_json(url, {
            "systemInstruction": {"parts": [{"text": ASK_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": question}]}],
        }, {})
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)


class ReplayEngine:
    """Serves previously saved answers. `answers` maps question -> answer text."""

    def __init__(self, name: str, answers: dict[str, str]):
        self.name = name
        self._answers = answers

    def ask(self, question: str) -> str:
        if question not in self._answers:
            raise KeyError(f"No saved {self.name} answer for: {question}")
        return self._answers[question]


LIVE_ENGINES = {"claude": ClaudeEngine, "openai": OpenAIEngine, "gemini": GeminiEngine}


def make_engine(name: str):
    if name not in LIVE_ENGINES:
        raise ValueError(f"Unknown engine '{name}'. Choose from: {', '.join(LIVE_ENGINES)}")
    return LIVE_ENGINES[name]()


def load_replay_engines(path: str | Path) -> list[ReplayEngine]:
    """Load a saved-answers file shaped {"engine": {"question": "answer", ...}, ...}."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [ReplayEngine(name, answers) for name, answers in raw.items() if not name.startswith("_")]


def collect_answers(engines, questions: list[str], cache_dir: str | Path | None = None,
                    log=print) -> list[Answer]:
    """Ask every engine every question. With a cache_dir, each answer is stored as
    one small JSON file keyed by engine + question, and reused on later runs."""
    cache = Path(cache_dir) if cache_dir else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)

    answers: list[Answer] = []
    for engine in engines:
        for q in questions:
            key = hashlib.sha256(f"{engine.name}|{q}".encode()).hexdigest()[:16]
            cached = cache / f"{engine.name}-{key}.json" if cache else None
            if cached and cached.exists():
                text = json.loads(cached.read_text(encoding="utf-8"))["text"]
                log(f"  [cache] {engine.name}: {q[:60]}")
            else:
                tag = "[saved]" if isinstance(engine, ReplayEngine) else "[ask]  "
                log(f"  {tag} {engine.name}: {q[:60]}")
                text = engine.ask(q)
                if cached:
                    cached.write_text(json.dumps({"engine": engine.name, "question": q, "text": text},
                                                 indent=2), encoding="utf-8")
            answers.append(Answer(engine=engine.name, question=q, text=text))
    return answers
