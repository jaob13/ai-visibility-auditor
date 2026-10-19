"""
server.py - the local web app. Start it with:   python -m auditor

It opens http://127.0.0.1:8765 in your browser. Nothing is hosted online: the
server only listens on your own computer, and API keys typed into the page are
held in memory for that request and never written to disk.

How a session flows (each step is a background "job" the page polls for progress):

  1. PLAN    POST /api/plan   the user's business info -> discover.build_plan
                               -> a draft list of competitors and questions
  2. REVIEW  (in the browser)  the user edits/approves the draft
  3. RUN     POST /api/run     the approved plan -> pipeline.run_audit -> scores
  4. EXPORT  GET  /api/export/<job>/<html|csv|json>   download the results
             GET  /api/report/<job>                   the report shown on the page

  POST /api/demo runs the bundled sample data, with no keys, so anyone can see it work.

Only the Python standard library is used, so there is nothing to install.
"""

from __future__ import annotations

import json
import re
import threading
import traceback
import uuid
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import load_config
from .discover import AuditPlan, BusinessInput, build_plan
from .engines import ClaudeEngine, load_replay_engines, make_engine
from .pipeline import run_audit
from .report import build_payload, render_csv, render_html

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
EXAMPLES = ROOT.parent / "examples"
CACHE = ROOT.parent / "runs" / "cache"

# Swappable in tests so the whole app can be exercised without real API calls.
ENGINE_FACTORY = make_engine
PLANNER_FACTORY = lambda key: ClaudeEngine(api_key=key)  # noqa: E731

JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


# ------------------------------------------------------------------ jobs

def _new_job(kind: str) -> dict:
    job = {"id": uuid.uuid4().hex[:12], "kind": kind, "status": "running", "log": [], "error": None}
    with _LOCK:
        JOBS[job["id"]] = job
    return job


def _start(job: dict, work) -> None:
    """Run `work(log)` in a background thread; capture its result or its error."""
    def log(msg: str) -> None:
        job["log"].append(str(msg))

    def runner() -> None:
        try:
            work(job, log)
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = str(e) or e.__class__.__name__
            log(f"Error: {job['error']}")
            traceback.print_exc()
    threading.Thread(target=runner, daemon=True).start()


def _finish_audit(job: dict, cfg, result, sample: bool) -> None:
    job["html"] = render_html(cfg, result, sample)
    job["csv"] = render_csv(result)
    job["json"] = json.dumps(build_payload(cfg, result, sample), indent=2)
    target = next(b for b in result.brands if b.is_target)
    job["summary"] = {"target": cfg.target.name, "score": target.score,
                      "mention_rate": target.mention_rate, "gaps": len(result.gaps),
                      "slug": re.sub(r"[^a-z0-9]+", "-", cfg.target.name.lower()).strip("-")}


def start_plan(body: dict) -> dict:
    keys = body.get("keys") or {}
    b = body.get("business") or {}
    inp = BusinessInput(
        name=str(b.get("name", "")), website=str(b.get("website", "")),
        what_you_do=str(b.get("what_you_do", "")), customers=str(b.get("customers", "")),
        difference=str(b.get("difference", "")), location=str(b.get("location", "")),
        scale=str(b.get("scale", "local")), radius_miles=int(b.get("radius_miles") or 25))
    inp.validate()                                    # bad input fails fast, before a job starts
    job = _new_job("plan")

    def work(job, log):
        planner = PLANNER_FACTORY(keys.get("anthropic"))
        job["plan"] = build_plan(inp, planner, keys.get("places") or None, log).to_dict()
    _start(job, work)
    return job


def start_run(body: dict) -> dict:
    keys = body.get("keys") or {}
    plan = AuditPlan.from_dict(body["plan"])
    cfg = plan.to_config()
    if not cfg.competitors:
        raise ValueError("Add at least one competitor.")
    if not cfg.questions:
        raise ValueError("Add at least one question.")
    names = body.get("engines") or ["claude"]
    engines = [ENGINE_FACTORY(n, api_key=keys.get({"claude": "anthropic"}.get(n, n))) for n in names]
    labeler = PLANNER_FACTORY(keys.get("anthropic")) if body.get("label") and keys.get("anthropic") else None
    job = _new_job("run")

    def work(job, log):
        result = run_audit(cfg, engines, labeler=labeler, cache_dir=CACHE, log=log)
        _finish_audit(job, cfg, result, sample=False)
        log("Done.")
    _start(job, work)
    return job


def start_demo() -> dict:
    job = _new_job("run")

    def work(job, log):
        cfg = load_config(EXAMPLES / "greenprint.json")
        engines = load_replay_engines(EXAMPLES / "sample_answers.json")
        result = run_audit(cfg, engines, log=log)
        _finish_audit(job, cfg, result, sample=True)
        log("Done (sample data).")
    _start(job, work)
    return job


def job_view(job: dict) -> dict:
    """What the browser is allowed to see about a job (never keys, never raw exports)."""
    view = {k: job.get(k) for k in ("id", "kind", "status", "log", "error", "plan", "summary")}
    return {k: v for k, v in view.items() if v is not None}


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    server_version = "AIVisibilityAuditor/0.2"

    def log_message(self, fmt, *args):  # keep the terminal quiet; job logs show progress
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data: dict) -> None:
        self._send(code, json.dumps(data).encode(), "application/json")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
        m = re.fullmatch(r"/api/job/(\w+)", path)
        if m:
            job = JOBS.get(m.group(1))
            return self._json(200, job_view(job)) if job else self._json(404, {"error": "unknown job"})
        m = re.fullmatch(r"/api/report/(\w+)", path)
        if m:
            job = JOBS.get(m.group(1))
            if not job or "html" not in job:
                return self._json(404, {"error": "no report yet"})
            return self._send(200, job["html"].encode(), "text/html; charset=utf-8")
        m = re.fullmatch(r"/api/export/(\w+)/(html|csv|json)", path)
        if m:
            job, fmt = JOBS.get(m.group(1)), m.group(2)
            if not job or fmt not in job:
                return self._json(404, {"error": "nothing to export"})
            ctype = {"html": "text/html", "csv": "text/csv", "json": "application/json"}[fmt]
            name = f"ai-visibility-{job['summary']['slug']}-{date.today()}.{fmt}"
            return self._send(200, job[fmt].encode(), f"{ctype}; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="{name}"'})
        self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        try:
            body = self._body()
            if self.path == "/api/plan":
                return self._json(200, job_view(start_plan(body)))
            if self.path == "/api/run":
                return self._json(200, job_view(start_run(body)))
            if self.path == "/api/demo":
                return self._json(200, job_view(start_demo()))
            self._json(404, {"error": "not found"})
        except (ValueError, KeyError, TypeError) as e:
            self._json(400, {"error": str(e)})


def serve(port: int = 8765, open_browser: bool = True) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"AI Visibility Auditor running at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
