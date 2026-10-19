"""
Tests for the planning stage and the web app. No real AI, map, or internet calls:
fake engines stand in for Claude so every path can be checked offline.

Run with:  python -m pytest -q
"""

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from auditor import server
from auditor.discover import (PLAN_SYSTEM_PROMPT, AuditPlan, BusinessInput, Competitor, build_plan,
                              domain_of, guard_plan, haversine_miles, page_summary)


# ----------------------------------------------------------- website reading

def test_domain_of_normalizes():
    assert domain_of("https://www.Example.com/about?x=1") == "example.com"
    assert domain_of("example.com") == "example.com"
    assert domain_of("") == ""


def test_page_summary_strips_scripts_and_tags():
    html = ("<html><head><title>Piel &amp; Co</title><meta name='description' content='Facials'>"
            "<script>var hidden=1</script></head><body><h1>Day spa</h1><p>Book now</p></body></html>")
    s = page_summary(html)
    assert s["title"] == "Piel & Co" and s["description"] == "Facials"
    assert "hidden" not in s["text"] and "Day spa Book now" in s["text"]


def test_haversine_known_distance():
    # Charlotte, NC to Raleigh, NC is about 130 miles in a straight line.
    assert 125 < haversine_miles(35.2271, -80.8431, 35.7796, -78.6382) < 135


# ------------------------------------------------------------------ the guard

INP = BusinessInput(name="Piel Body Spa", website="pielbodyspa.com", what_you_do="day spa",
                    location="Charlotte, NC", scale="local", radius_miles=20)


def test_guard_drops_self_duplicates_and_branded_questions():
    ai = {"category": "day spa", "aliases": ["Piel Spa"],
          "competitors": [{"name": "Hand & Stone", "website": "https://www.handandstone.com/x"},
                          {"name": "hand & stone", "website": ""},          # duplicate
                          {"name": "Piel Spa", "website": ""},              # the target's alias
                          {"name": "Other Spa", "website": "pielbodyspa.com"}],  # target's domain
          "questions": ["Best spa in Charlotte?", "Is Hand & Stone good?", "Best spa in Charlotte?",
                        "Where is Piel Spa?"]}
    plan = guard_plan(INP, "pielbodyspa.com", ai, places=[])
    assert [c.name for c in plan.competitors] == ["Hand & Stone"]
    assert plan.competitors[0].domains == ["handandstone.com"]
    assert plan.questions == ["Best spa in Charlotte?"]
    assert plan.target_aliases == ["Piel Spa"]
    assert any("Removed 2 question" in n for n in plan.notes)


def test_guard_puts_map_competitors_first():
    places = [Competitor("Spa Near You", ["spanear.com"], source="places", detail="3.1 mi away")]
    plan = guard_plan(INP, "pielbodyspa.com", {"competitors": [{"name": "Massage Envy"}], "questions": ["q?"]}, places)
    assert [(c.name, c.source) for c in plan.competitors] == [("Spa Near You", "places"), ("Massage Envy", "ai")]


def test_input_validation():
    with pytest.raises(ValueError, match="Location"):
        BusinessInput(name="X", website="", what_you_do="y", scale="local").validate()
    with pytest.raises(ValueError, match="Radius"):
        BusinessInput(name="X", website="", what_you_do="y", location="A", radius_miles=500).validate()
    BusinessInput(name="X", website="", what_you_do="y", scale="national").validate()  # no location needed


def test_plan_round_trips_to_config():
    plan = AuditPlan("Piel Body Spa", ["Piel Spa"], ["pielbodyspa.com"], "day spa",
                     [Competitor("Hand & Stone", ["handandstone.com"])], ["Best spa?"])
    again = AuditPlan.from_dict(json.loads(json.dumps(plan.to_dict())))
    cfg = again.to_config()
    assert cfg.target.names == ("Piel Body Spa", "Piel Spa") and cfg.competitors[0].domains == ("handandstone.com",)


# ------------------------------------------------------------ web app, end to end

class FakeClaude:
    name = "claude"

    def ask(self, prompt, system=None, max_tokens=0):
        if system == PLAN_SYSTEM_PROMPT:
            return json.dumps({"category": "day spa", "competitors": [{"name": "Hand & Stone"}],
                               "questions": ["Best spa in Charlotte?"]})
        if system:
            return '{"stances": {}, "other_products": []}'
        return "Hand & Stone is popular. Piel Body Spa is great too."


@pytest.fixture(scope="module")
def app():
    server.PLANNER_FACTORY = lambda key: FakeClaude()
    server.ENGINE_FACTORY = lambda name, api_key=None: FakeClaude()
    import auditor.discover as d
    d.fetch_website = lambda url: {"error": "offline test"}   # no internet in tests
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _call(base, path, body=None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        ctype = r.headers.get("Content-Type", "")
        raw = r.read().decode()
        return json.loads(raw) if "json" in ctype else (raw, r.headers)


def _wait(base, job_id):
    for _ in range(100):
        j = _call(base, f"/api/job/{job_id}")
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job never finished")


def test_full_flow_plan_run_export(app):
    biz = {"name": "Piel Body Spa", "website": "pielbodyspa.com", "what_you_do": "day spa",
           "location": "Charlotte, NC", "scale": "local", "radius_miles": 20}
    plan_job = _wait(app, _call(app, "/api/plan", {"business": biz, "keys": {"anthropic": "x"}})["id"])
    assert plan_job["status"] == "done"
    plan = plan_job["plan"]
    assert plan["competitors"][0]["name"] == "Hand & Stone"

    run_job = _wait(app, _call(app, "/api/run", {"plan": plan, "keys": {"anthropic": "x"},
                                                 "engines": ["claude"], "label": True})["id"])
    assert run_job["status"] == "done", run_job.get("error")
    assert run_job["summary"]["score"] > 0
    assert "keys" not in json.dumps(run_job)          # job view never echoes secrets

    csv_text, headers = _call(app, f"/api/export/{run_job['id']}/csv")
    assert csv_text.startswith("brand,is_target,score")
    assert 'filename="ai-visibility-piel-body-spa-' in headers["Content-Disposition"]
    report, _ = _call(app, f"/api/report/{run_job['id']}")
    assert "AI visibility audit: Piel Body Spa" in report


def test_demo_runs_without_keys(app):
    j = _wait(app, _call(app, "/api/demo", {})["id"])
    assert j["summary"]["score"] == 11.4              # same canary as the CLI


def test_bad_input_is_rejected_before_any_job(app):
    with pytest.raises(urllib.error.HTTPError) as e:
        _call(app, "/api/plan", {"business": {"name": "", "what_you_do": "x", "scale": "national"}})
    assert e.value.code == 400
