"""
Canary tests. Run with:  python -m pytest -q

A "canary" pins down a known-correct result. If someone changes the matching,
the guard, or the scoring math and a number moves, a canary fails and says so
before a wrong score ever reaches a report. Same idea as the Command Center's
canary baselines (NSB 5.49 / Allbirds 6.43), applied to this tool.

None of these tests call a real AI or the internet.
"""

from pathlib import Path

import pytest

from auditor.config import Brand, AuditConfig, load_config
from auditor.engines import collect_answers, load_replay_engines
from auditor.extract import apply_guard, extract, extract_rules, find_mentions
from auditor.score import WEIGHTS, score_audit, visibility_score

ROOT = Path(__file__).resolve().parents[1]
BRANDS = [
    Brand("GreenPrint", ("Green Print",), ("getgreenprint.app",), is_target=True),
    Brand("Jobber", (), ("getjobber.com",)),
    Brand("Housecall Pro", ("HousecallPro",), ("housecallpro.com",)),
]


# ---------------------------------------------------------------- matching

def test_mentions_ranked_by_first_appearance():
    text = "Try Housecall Pro. Jobber is fine too. Green Print is new."
    assert find_mentions(text, BRANDS) == ["Housecall Pro", "Jobber", "GreenPrint"]


def test_aliases_and_case_count_as_same_brand():
    assert find_mentions("housecallpro and JOBBER", BRANDS) == ["Housecall Pro", "Jobber"]


def test_whole_word_only():
    # "Jobbers" is not "Jobber"; partial words must not count as mentions.
    assert find_mentions("Jobbers and job boards", BRANDS) == []


def test_domain_counts_as_citation_and_mention():
    ex = extract_rules("Details at getgreenprint.app", BRANDS)
    assert ex.ranked == ["GreenPrint"]
    assert ex.cited == {"GreenPrint"}


# ------------------------------------------------------------------- guard

def test_guard_rejects_brands_not_in_text():
    rules = extract_rules("Jobber is the best choice.", BRANDS)
    ai_claims = {"stances": {"Jobber": "recommended", "GreenPrint": "recommended"},
                 "other_products": ["Jobber", "Yardbook"]}
    merged = apply_guard(rules, ai_claims)
    assert merged.stance == {"Jobber": "recommended"}   # GreenPrint claim discarded
    assert merged.rejected == ["GreenPrint"]
    assert merged.others == ["Yardbook"]                 # tracked names never listed as "other"
    assert merged.ranked == ["Jobber"]                   # rank still comes from the text


def test_guard_ignores_invalid_stance_labels():
    rules = extract_rules("Jobber works.", BRANDS)
    merged = apply_guard(rules, {"stances": {"Jobber": "amazing"}})
    assert merged.stance == {"Jobber": "neutral"}


def test_labeler_failure_falls_back_to_rules():
    class BrokenLabeler:
        def ask(self, *a, **k):
            return "sorry, no JSON here"
    ex = extract("Jobber is good.", BRANDS, labeler=BrokenLabeler())
    assert ex.method == "rules" and ex.ranked == ["Jobber"] and "failed" in ex.note


def test_labeler_success_path():
    class FakeLabeler:
        def ask(self, *a, **k):
            return '```json\n{"stances": {"Jobber": "negative"}, "other_products": []}\n```'
    ex = extract("Avoid Jobber.", BRANDS, labeler=FakeLabeler())
    assert ex.method == "rules+ai" and ex.stance == {"Jobber": "negative"}


# ----------------------------------------------------------------- scoring

def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_perfect_and_zero_scores():
    assert visibility_score({k: 1.0 for k in WEIGHTS}) == 100.0
    assert visibility_score({k: 0.0 for k in WEIGHTS}) == 0.0


def test_demo_canary_baseline():
    """Pinned scores for the bundled sample data. If this fails, the scoring or
    matching logic changed: confirm the change is intended, then update the numbers."""
    cfg = load_config(ROOT / "examples" / "greenprint.json")
    engines = load_replay_engines(ROOT / "examples" / "sample_answers.json")
    answers = collect_answers(engines, cfg.questions, log=lambda *_: None)
    res = score_audit(cfg, [(a, extract(a.text, cfg.brands)) for a in answers])
    scores = {b.brand: b.score for b in res.brands}
    assert scores == {"Housecall Pro": 71.9, "Jobber": 54.0, "ServiceTitan": 29.7,
                      "Workiz": 29.7, "GreenPrint": 11.4}
    assert len(res.gaps) == 10
    assert res.target_by_engine == {"sample_a": 22.7, "sample_b": 0.0}


def test_config_rejects_shared_alias(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"target": {"name": "A", "aliases": ["X"]}, '
                   '"competitors": [{"name": "B", "aliases": ["x"]}], "questions": ["q?"]}')
    with pytest.raises(ValueError, match="used by both"):
        load_config(bad)
