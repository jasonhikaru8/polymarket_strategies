"""Decision gates reject stale, mismatched or dependent evidence before order handling."""
from copy import deepcopy
import math

import pytest

from polymarket_strategies.strategies import evaluate

NOW = 1_800_000_000
CONTRACT = {"now": NOW, "end_time": NOW + 30 * 86_400,
            "resolution_source": "Official result", "yes_definition": "The specified event happens."}


def model():
    return {"kind": "model_value", "min_edge": 0.02, "inputs": {
        "probability_yes": 0.65, "conservative_low_yes": 0.60, "conservative_high_yes": 0.70,
        "as_of": NOW - 60, "valid_until": NOW + 300,
        "target_yes_definition": CONTRACT["yes_definition"], "resolution_source": CONTRACT["resolution_source"],
        "evidence": "Independent reader forecast", "source_notes": "Frozen before this quote",
    }}


def decision(strategy, **changes):
    arguments = {**CONTRACT, "outcome": "YES", "limit_price": 0.55, "fee_per_share": 0.01, **changes}
    return evaluate(strategy, **arguments)


def mentions():
    strategy = model()
    strategy["kind"] = "mention_base_rate"
    strategy["inputs"] = {key: strategy["inputs"][key]
                          for key in ("target_yes_definition", "resolution_source", "evidence", "source_notes")}
    strategy["inputs"].update(cohort="Comparable speeches", comparability_reviewed=True, min_events=100)
    strategy["inputs"]["events"] = [
        {"event_id": f"e-{i}", "group": f"g-{i}", "outcome_yes": i < 100,
         "resolved_at": NOW - (i + 1), "cohort": "Comparable speeches",
         "resolution_source": CONTRACT["resolution_source"], "yes_definition": CONTRACT["yes_definition"]}
        for i in range(120)]
    return strategy


def test_value_uses_conservative_bound_and_entry_fee():
    result = decision(model())
    assert result["eligible"] and result["probability"] == 0.65
    assert result["conservative_probability"] == 0.60
    assert result["edge_per_share"] == pytest.approx(0.04)
    assert not decision(model(), fee_per_share=0.04)["eligible"]


def test_no_uses_upper_yes_bound_not_lower():
    result = decision(model(), outcome="NO", limit_price=0.20, fee_per_share=0.005)
    assert result["eligible"]
    assert result["probability"] == pytest.approx(0.35)
    assert result["conservative_probability"] == pytest.approx(0.30)
    assert result["edge_per_share"] == pytest.approx(0.095)


@pytest.mark.parametrize("field,value", [
    ("as_of", NOW + 1), ("valid_until", NOW),
    ("target_yes_definition", "A different event"), ("resolution_source", "An unofficial rumor"),
    ("probability_yes", math.nan), ("conservative_low_yes", 0.80),
    ("conservative_high_yes", 1.01), ("evidence", ""), ("source_notes", ""),
])
def test_value_rejects_bad_forecast(field, value):
    strategy = model()
    strategy["inputs"][field] = value
    assert not decision(strategy)["eligible"]


@pytest.mark.parametrize("changes", [
    {"limit_price": 0}, {"limit_price": 1}, {"fee_per_share": -0.01},
    {"limit_price": math.inf}, {"fee_per_share": True}, {"now": math.nan},
    {"end_time": NOW}, {"outcome": "UP"}, {"resolution_source": ""}, {"yes_definition": ""},
])
def test_invalid_order_assumptions_are_rejected(changes):
    assert not decision(model(), **changes)["eligible"]


@pytest.mark.parametrize("field", ["min_edge", "inputs"])
def test_required_configuration_cannot_be_silently_defaulted(field):
    strategy = model()
    del strategy[field]
    result = decision(strategy)
    assert not result["eligible"] and "missing required field" in result["reasons"][0]


def test_manual_has_no_fabricated_forecast():
    result = decision({"kind": "manual", "min_edge": 0, "inputs": {}})
    assert result["eligible"]
    assert result["probability"] is result["conservative_probability"] is result["edge_per_share"] is None


def test_manual_cannot_claim_a_minimum_edge_was_checked():
    result = decision({"kind": "manual", "min_edge": 0.01, "inputs": {}})
    assert not result["eligible"] and "min_edge must be zero" in result["reasons"][0]


def test_carry_checks_price_lockup_and_expected_return_for_either_outcome():
    strategy = model()
    strategy["kind"] = "favorite_carry"
    strategy["min_edge"] = 0.005
    strategy["inputs"].update(probability_yes=0.985, conservative_low_yes=0.977, conservative_high_yes=0.992,
                              min_favorite_price=0.90, min_expected_annual_return=0.10, max_days=90)
    assert decision(strategy, limit_price=0.96, fee_per_share=0.001536)["eligible"]
    assert not decision(strategy, limit_price=0.98, fee_per_share=0.001536)["eligible"]
    assert not decision(strategy, limit_price=0.89, fee_per_share=0.001536)["eligible"]
    assert not decision(strategy, limit_price=0.96, end_time=NOW + 91 * 86_400)["eligible"]
    strict_return = deepcopy(strategy)
    strict_return["inputs"]["min_expected_annual_return"] = 0.30
    assert not decision(strict_return, limit_price=0.96, fee_per_share=0.001536)["eligible"]
    strategy["inputs"].update(probability_yes=0.015, conservative_low_yes=0.008, conservative_high_yes=0.023)
    assert decision(strategy, outcome="NO", limit_price=0.96, fee_per_share=0.001536)["eligible"]


def test_mention_empirical_probability_and_conservative_no_bound():
    result = decision(mentions(), limit_price=0.62)
    assert result["eligible"] and result["probability"] == pytest.approx(100 / 120)
    assert 0.75 < result["conservative_probability"] < 0.77
    no = decision(mentions(), outcome="NO", limit_price=0.05)
    assert no["eligible"] and no["probability"] == pytest.approx(20 / 120)
    assert 0.10 < no["conservative_probability"] < 0.12


@pytest.mark.parametrize("field,value", [
    ("group", "g-1"), ("event_id", "e-1"), ("outcome_yes", 1),
    ("resolved_at", NOW), ("cohort", "Another type of speech"),
    ("resolution_source", "Edited media excerpt"), ("yes_definition", "Different word"),
])
def test_mention_rejects_duplicate_ambiguous_or_noncomparable_events(field, value):
    strategy = mentions()
    strategy["inputs"]["events"][0][field] = value
    assert not decision(strategy)["eligible"]


def test_mention_requires_review_and_minimum_sample_without_defaults():
    strategy = mentions()
    strategy["inputs"]["comparability_reviewed"] = False
    assert not decision(strategy)["eligible"]
    strategy = mentions()
    strategy["inputs"]["min_events"] = 121
    assert not decision(strategy)["eligible"]
    strategy["inputs"]["min_events"] = 1
    assert not decision(strategy)["eligible"]
    del strategy["inputs"]["source_notes"]
    assert not decision(strategy)["eligible"]
