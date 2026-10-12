"""Offline model decisions: no market requests, credentials, signing or orders."""
import copy
import json
import math

import pytest

from polymarket_strategies.strategy_models import INDICES, analyze, demo_inputs

NOW = 2_000_000_000
FORECASTS = {7, 10, 11, 12, 13, 19, 20, 32, 33}


@pytest.mark.parametrize("index", INDICES)
def test_complete_synthetic_schemas(index):
    inputs = demo_inputs(index, NOW)
    original = copy.deepcopy(inputs)
    result = analyze(index, inputs, now=NOW)
    assert result["eligible"] is True, result["reasons"]
    assert bool(result.get("forecast")) == (index in FORECASTS)
    assert inputs == original
    assert "SYNTHETIC" in inputs["evidence"]
    json.dumps(inputs, allow_nan=False)
    json.dumps(result, allow_nan=False)
    if index in FORECASTS:
        forecast = result["forecast"]
        assert forecast["conservative_low_yes"] <= forecast["probability_yes"] <= forecast["conservative_high_yes"]
        assert forecast["target_yes_definition"] == inputs["contract"]["yes_definition"]
        assert forecast["resolution_source"] == inputs["contract"]["resolution_source"]


@pytest.mark.parametrize("index", INDICES)
@pytest.mark.parametrize("change", ("expired", "mismatched_source", "missing_evidence", "nested_nan"))
def test_all_models_reject_invalid_evidence_context(index, change):
    inputs = demo_inputs(index, NOW)
    if change == "expired":
        inputs["valid_until"] = NOW
    elif change == "mismatched_source":
        inputs["contract"]["resolution_source"] = "https://example.invalid/different-source"
    elif change == "missing_evidence":
        del inputs["evidence"]
    else:
        inputs["unused_reader_note"] = {"value": float("nan")}
    result = analyze(index, inputs, now=NOW)
    assert not result["eligible"]
    assert result["reasons"]
    assert "forecast" not in result
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field,value", (("as_of", NOW + 1), ("min_edge", -0.1), ("outcome", "MAYBE"),
                                         ("limit_price", 1), ("fee_per_share", -0.01),
                                         ("probability_yes", True)))
def test_common_decision_bounds(field, value):
    inputs = demo_inputs(10, NOW)
    inputs[field] = value
    assert not analyze(10, inputs, now=NOW)["eligible"]


def test_definition_mismatch_and_closed_contract():
    inputs = demo_inputs(10, NOW)
    inputs["contract"]["yes_definition"] += " with a different rule"
    assert "definition" in analyze(10, inputs, now=NOW)["reasons"][0]
    inputs = demo_inputs(10, NOW)
    inputs["contract"]["end_time"] = NOW
    assert not analyze(10, inputs, now=NOW)["eligible"]


def test_no_uses_upper_yes_stress_bound():
    inputs = demo_inputs(10, NOW)
    inputs.update(outcome="NO", probability_yes=0.2, conservative_low_yes=0.1, conservative_high_yes=0.3)
    result = analyze(10, inputs, now=NOW)
    assert result["eligible"]
    assert result["analysis"]["decision"]["conservative_probability"] == pytest.approx(0.7)
    assert result["analysis"]["decision"]["edge_per_share"] == pytest.approx(0.34)


@pytest.mark.parametrize("field,value", (("min_favorite_price", 0.99), ("max_days", 1),
                                         ("min_expected_annual_return", 1)))
def test_favorite_specific_requirements_survive_shared_forecast(field, value):
    inputs = demo_inputs(7, NOW)
    inputs[field] = value
    result = analyze(7, inputs, now=NOW)
    assert not result["eligible"]
    assert result["forecast"]["probability_yes"] == 0.995


def test_holding_reward_estimate_is_separate_from_actual_receipts_and_probability():
    inputs = demo_inputs(8, NOW)
    result = analyze(8, inputs, now=NOW)
    assert result["analysis"]["estimated_rewards"] == pytest.approx(100 * 0.96 * 0.0325 * 30 / 365)
    assert result["analysis"]["actual_rewards_received"] == 0
    assert "forecast" not in result
    inputs["reward_eligibility_verified"] = False
    assert not analyze(8, inputs, now=NOW)["eligible"]
    inputs["reward_eligibility_verified"] = True
    inputs["probability_yes"] = 0.5
    assert not analyze(8, inputs, now=NOW)["eligible"]


def test_holding_reward_cannot_assume_early_resolution_to_understate_lockup_cost():
    inputs = demo_inputs(8, NOW)
    inputs["holding_days"] = 1
    result = analyze(8, inputs, now=NOW)
    assert result["reasons"] == ["positive shares and holding_days must cover the scheduled settlement horizon"]


def test_holding_rewards_stop_at_scheduled_settlement_while_alternative_cost_covers_the_budget():
    inputs = demo_inputs(8, NOW)
    inputs["holding_days"] = 40  # the contract is scheduled to settle in 30 days
    analysis = analyze(8, inputs, now=NOW)["analysis"]
    assert analysis["estimated_rewards"] == pytest.approx(100 * 0.96 * 0.0325 * 30 / 365)
    cost = 100 * (0.95 + 0.01)
    assert analysis["estimated_net_after_alternative"] == pytest.approx(
        100 * 0.99 - cost + 100 * 0.96 * 0.0325 * 30 / 365 - cost * 0.04 * 40 / 365)


@pytest.mark.parametrize("field", ("reward_rate_annual", "alternative_rate_annual"))
def test_annual_rates_are_fractions_not_percent(field):
    inputs = demo_inputs(8, NOW)
    inputs[field] = 3.25
    assert analyze(8, inputs, now=NOW)["reasons"] == [f"{field} is outside its permitted range"]


def test_ensemble_replication_does_not_shrink_uncertainty():
    inputs = demo_inputs(11, NOW)
    original = analyze(11, inputs, now=NOW)
    inputs["members"] *= 20
    repeated = analyze(11, inputs, now=NOW)
    assert original["forecast"] == repeated["forecast"]
    assert original["forecast"]["probability_yes"] == pytest.approx(0.75)
    assert "not independent" in original["analysis"]["assumption"]


@pytest.mark.parametrize("field,value,reason", (
    ("measurement_reviewed", False, "station, units, local date and settlement measurement must be reviewed"),
    ("bucket_upper", 19.5, "bucket_lower must be below bucket_upper"),
    ("members", [20], "members must contain at least two ensemble measurements"),
    ("uncertainty_allowance", 0, "uncertainty_allowance must be positive")))
def test_weather_requires_semantics_and_model_uncertainty(field, value, reason):
    inputs = demo_inputs(11, NOW)
    inputs[field] = value
    assert analyze(11, inputs, now=NOW)["reasons"] == [reason]


def test_weather_buckets_are_half_open_so_reported_values_count_once():
    inputs = demo_inputs(11, NOW)
    # Unrounded highs that a whole-degree station reports as 78 or 79: bounds 77.5 and 79.5 catch all six.
    inputs.update(bucket_lower=77.5, bucket_upper=79.5, members=[77.6, 77.9, 78.2, 78.6, 79.1, 79.4],
                  probability_bias_adjustment=0)
    assert analyze(11, inputs, now=NOW)["analysis"]["raw_member_frequency"] == 1
    # 79.5 belongs to the next bucket only, so neighboring buckets add to one.
    inputs["members"] = [79.5, 79.5, 78.0, 81.0]
    low = analyze(11, inputs, now=NOW)["analysis"]["raw_member_frequency"]
    inputs.update(bucket_lower=79.5, bucket_upper=81.5)
    high = analyze(11, inputs, now=NOW)["analysis"]["raw_member_frequency"]
    assert (low, high) == (0.25, 0.75)


def test_llm_weighting_is_sourced_and_human_reviewed():
    inputs = demo_inputs(12, NOW)
    inputs["forecasts"][1]["weight"] = 3
    result = analyze(12, inputs, now=NOW)
    assert result["forecast"]["probability_yes"] == pytest.approx(0.7125)
    inputs["human_reviewed"] = False
    assert not analyze(12, inputs, now=NOW)["eligible"]


@pytest.mark.parametrize("change", ("zero_weights", "unsourced", "duplicate_model", "negative_weight"))
def test_llm_invalid_inputs(change):
    inputs = demo_inputs(12, NOW)
    if change == "zero_weights":
        for forecast in inputs["forecasts"]:
            forecast["weight"] = 0
    elif change == "unsourced":
        inputs["forecasts"][0]["source"] = ""
    elif change == "duplicate_model":
        inputs["forecasts"][1]["model"] = inputs["forecasts"][0]["model"]
    else:
        inputs["forecasts"][0]["weight"] = -1
    assert not analyze(12, inputs, now=NOW)["eligible"]


def test_options_reference_is_not_automatically_actual_probability():
    inputs = demo_inputs(13, NOW)
    inputs["probability_adjustment"] = -0.1
    result = analyze(13, inputs, now=NOW)
    assert result["analysis"]["option_implied_reference"] == pytest.approx(0.7)
    assert result["forecast"]["probability_yes"] == pytest.approx(0.6)
    assert "risk-neutral" in result["analysis"]["assumption"]
    assert "not statistical confidence" in result["analysis"]["assumption"]
    inputs["risk_neutral_to_real_reviewed"] = False
    assert not analyze(13, inputs, now=NOW)["eligible"]


@pytest.mark.parametrize("field,value", (("strike_width", 0), ("call_high_cost", 200),
                                         ("probability_adjustment", 0.5), ("conservative_low_yes", 0.8)))
def test_options_malformed_or_unbounded_reference(field, value):
    inputs = demo_inputs(13, NOW)
    inputs[field] = value
    assert not analyze(13, inputs, now=NOW)["eligible"]


def test_options_adjustment_outside_zero_one_names_the_adjustment():
    inputs = demo_inputs(13, NOW)
    inputs["probability_adjustment"] = 0.5  # 0.7 reference + 0.5
    assert analyze(13, inputs, now=NOW)["reasons"] == [
        "option-implied reference plus probability_adjustment must lie between 0 and 1"]


def _december_rung(**changes):
    # Chapter 10's December "hit $150k" rung: the $140,000/$160,000 call spread costs $61.29 of a $20,000 width (0.31% finish-above);
    # the chapter's touch model gives 1.78%. Buying NO at 0.977 pays a 0.157-cent fee.
    inputs = demo_inputs(13, NOW)
    inputs.update(call_low_cost=124.44, call_high_cost=63.15, strike_width=20_000, outcome="NO", limit_price=0.977,
                  fee_per_share=0.00157, min_edge=0, conservative_low_yes=0, conservative_high_yes=0.0178, **changes)
    return inputs


def test_options_tool_refuses_a_touch_market_without_a_touch_conversion():
    inputs = _december_rung(payoff_type="touch")
    result = analyze(13, inputs, now=NOW)
    assert result["eligible"] is False and "forecast" not in result
    assert result["reasons"][0].startswith("a touch market needs touch_probability")
    inputs.update(touch_probability=0.0178, touch_conversion_notes="touch_probability(84612, 150000, 0.5014, 93.3): the forward, the $150,000 call's volatility")
    result = analyze(13, inputs, now=NOW)
    assert result["analysis"]["payoff_reference"] == 0.0178 and result["forecast"]["probability_yes"] == pytest.approx(0.0178)
    # NO is worth 1 - 0.0178 = 0.9822 against 0.977 + 0.00157: +0.36 cents, the chapter's figure, not the +1.84 a finish-above reference gives.
    assert result["analysis"]["decision"]["edge_per_share"] == pytest.approx(0.00363, abs=1e-6)
    del inputs["touch_conversion_notes"]
    assert analyze(13, inputs, now=NOW)["reasons"] == ["missing required field: touch_conversion_notes"]


def test_options_tool_states_the_payoff_type_and_takes_a_finish_above_reference_only_as_such():
    result = analyze(13, _december_rung(payoff_type="finish_above"), now=NOW)
    assert result["analysis"]["option_implied_reference"] == pytest.approx(61.29 / 20_000)
    assert result["analysis"]["payoff_type"] == "finish_above"
    assert result["analysis"]["decision"]["edge_per_share"] == pytest.approx(1 - 0.0178 - 0.97857, abs=1e-9)  # the stress bound, not the 0.31%
    for payoff in (None, "terminal", "hit"):
        inputs = _december_rung(payoff_type=payoff)
        assert analyze(13, inputs, now=NOW)["reasons"] == ["payoff_type must be finish_above, touch or range"]
    inputs = _december_rung()
    del inputs["payoff_type"]
    assert analyze(13, inputs, now=NOW)["reasons"] == ["missing required field: payoff_type"]


def test_options_tool_prices_a_range_as_the_difference_of_two_finish_above_references():
    inputs = demo_inputs(13, NOW)  # first spread 0.70: finishing above the range's lower level
    inputs.update(payoff_type="range", upper_call_low_cost=60, upper_call_high_cost=20, upper_strike_width=100,  # 0.40 above its upper level
                  conservative_low_yes=0.2, conservative_high_yes=0.4)
    result = analyze(13, inputs, now=NOW)
    assert result["analysis"]["upper_option_implied_reference"] == pytest.approx(0.4)
    assert result["forecast"]["probability_yes"] == pytest.approx(0.3)
    inputs.update(upper_call_low_cost=100, upper_call_high_cost=10)  # 0.90 above the upper level is more than 0.70 above the lower one
    assert analyze(13, inputs, now=NOW)["reasons"] == [
        "the upper call spread's finish-above reference exceeds the lower one's; check the range's strikes"]


def test_twap_exact_observation_count_and_analysis_only():
    inputs = demo_inputs(14, NOW)
    result = analyze(14, inputs, now=NOW)
    assert result["eligible"] and "forecast" not in result
    # Average of 39 x 100.01, 100.02 and 20 future ticks from 100.02 against 100, sd 0.01 x sqrt(20 x 21 x 41 / 6).
    assert result["analysis"]["model_probability_up"] == pytest.approx(0.934730, abs=1e-6)
    assert result["analysis"]["edge_per_share"] == pytest.approx(0.934730 - 0.35 - 0.01, abs=1e-6)
    inputs["observed_prices"].pop()
    assert not analyze(14, inputs, now=NOW)["eligible"]
    inputs.update(observed_prices=[100] * 60, seconds_left=0, sigma_per_second=0)
    assert analyze(14, inputs, now=NOW)["analysis"]["model_probability_up"] == 1


@pytest.mark.parametrize("outcome,price,min_edge", (("YES", 0.98, 0.5), ("NO", 0.90, 0.02)))
def test_twap_screen_compares_the_model_with_price_fee_and_min_edge(outcome, price, min_edge):
    inputs = demo_inputs(14, NOW)
    inputs.update(outcome=outcome, limit_price=price, min_edge=min_edge)
    result = analyze(14, inputs, now=NOW)
    assert result["eligible"] is False
    assert result["reasons"] == ["model probability after the entry fee is below min_edge"]


@pytest.mark.parametrize("change", ("duplicate_groups", "wrong_definition", "future_event", "unreviewed"))
def test_mentions_reuse_comparability_requirements(change):
    inputs = demo_inputs(19, NOW)
    if change == "duplicate_groups":
        inputs["events"][1]["group"] = inputs["events"][0]["group"]
    elif change == "wrong_definition":
        inputs["events"][0]["yes_definition"] = "different count semantics"
    elif change == "future_event":
        inputs["events"][0]["resolved_at"] = NOW
    else:
        inputs["comparability_reviewed"] = False
    result = analyze(19, inputs, now=NOW)
    assert not result["eligible"]
    assert "forecast" not in result


@pytest.mark.parametrize("said", (False, True))
def test_mentions_accept_unanimous_histories(said):
    inputs = demo_inputs(19, NOW)
    for event in inputs["events"]:
        event["outcome_yes"] = said
    inputs.update(outcome="YES" if said else "NO", limit_price=0.70)
    result = analyze(19, inputs, now=NOW)
    assert result["eligible"] is True, result["reasons"]
    # Wilson 95% for 0 of 20 runs from 0 to 2 x (1.96^2 / 40) / (1 + 1.96^2 / 20) = 0.1611301; 20 of 20 mirrors it.
    assert result["analysis"]["decision"]["conservative_probability"] == pytest.approx(1 - 0.1611301, abs=1e-7)


def test_count_cannot_finish_below_observed_and_no_trade_uses_complement():
    inputs = demo_inputs(20, NOW)
    inputs.update(observed_count=300, outcome="NO")
    result = analyze(20, inputs, now=NOW)
    assert result["eligible"]
    assert result["forecast"]["probability_yes"] == 0
    assert result["analysis"]["decision"]["conservative_probability"] == pytest.approx(0.95)


def test_count_zero_future_pace_and_open_upper_bucket():
    inputs = demo_inputs(20, NOW)
    inputs.update(observed_count=200, pace_per_day=0, stress_paces=[0], count_upper=None)
    result = analyze(20, inputs, now=NOW)
    assert result["forecast"]["probability_yes"] == 1
    assert result["analysis"]["future_count_standard_deviation"] == 0


@pytest.mark.parametrize("field,value", (("variance_multiplier", 0.5), ("stress_paces", []),
                                         ("count_upper", 100), ("observed_count", 1.5),
                                         ("days_remaining", 31), ("settlement_counter_reviewed", False)))
def test_count_requires_correct_counter_and_stress_model(field, value):
    inputs = demo_inputs(20, NOW)
    inputs[field] = value
    assert not analyze(20, inputs, now=NOW)["eligible"]


def _count(inputs, observed, lower, upper, pace, days, variance):
    inputs.update(observed_count=observed, count_lower=lower, count_upper=upper, pace_per_day=pace,
                  days_remaining=days, variance_multiplier=variance)
    return analyze(20, inputs, now=NOW)


@pytest.mark.parametrize("lower,book", ((160, 0.1427), (180, 0.2400), (200, 0.2593), (220, 0.1800), (240, 0.0802)))
def test_count_reports_chapter_12_bell_curve_beside_the_negative_binomial(lower, book):
    # Chapter 12 toy: 58 posts, 29 a day for 5 more days, variance six times the 145 still to come.
    result = _count(demo_inputs(20, NOW), 58, lower, lower + 19, 29, 5, 6)
    assert result["analysis"]["normal_approximation_probability"] == pytest.approx(book, abs=5e-5)
    negative_binomial = {160: 0.160757, 180: 0.258599, 200: 0.249472, 220: 0.161053, 240: 0.075261}[lower]
    assert result["forecast"]["probability_yes"] == pytest.approx(negative_binomial, abs=1e-6)


def test_count_late_in_the_window_uses_a_count_distribution_not_a_bell_curve():
    # 195 posts so far, 6 hours left at 29 a day (mean 7.25), variance multiplier 6, bucket 200-219.
    inputs = demo_inputs(20, NOW)
    inputs.update(stress_paces=[29], stress_variances=[6])
    result = _count(inputs, 195, 200, 219, 29, 0.25, 6)
    assert result["forecast"]["probability_yes"] == pytest.approx(0.549738, abs=1e-6)
    assert result["analysis"]["normal_approximation_probability"] == pytest.approx(0.746794, abs=1e-6)


def test_count_poisson_case_and_small_mean_bell_curve_conditioning():
    inputs = demo_inputs(20, NOW)
    inputs.update(stress_paces=[2], stress_variances=[1])
    assert _count(inputs, 10, 10, 10, 2, 1, 1)["forecast"]["probability_yes"] == pytest.approx(math.exp(-2))
    inputs.update(stress_variances=[6])
    # Bell curve at mean 2, variance 12, renormalized above -0.5: 0.127177 (0.097260 without conditioning).
    result = _count(inputs, 0, 0, 0, 2, 1, 6)
    assert result["analysis"]["normal_approximation_probability"] == pytest.approx(0.127177, abs=1e-6)


def test_count_demo_stresses_the_wider_spreads_the_book_measured():
    # Chapter 12's toy multiplier is 6; the book's weekly count data imply about 16 to 22, so the demo also stresses 16 and 24.
    inputs = demo_inputs(20, NOW)
    assert (inputs["variance_multiplier"], inputs["stress_variances"]) == (6, [6, 16, 24])
    result = analyze(20, inputs, now=NOW)
    assert result["eligible"] is True and result["analysis"]["stress_scenarios"] == 9  # paces 25, 33 and 29 by multipliers 6, 16 and 24, each once
    narrow = analyze(20, {**inputs, "stress_variances": [4, 8]}, now=NOW)  # the 0.4.0 demo
    assert result["forecast"]["probability_yes"] == narrow["forecast"]["probability_yes"]
    assert result["forecast"]["conservative_low_yes"] < narrow["forecast"]["conservative_low_yes"] - 0.05


def test_count_model_refuses_parameters_too_large_to_sum():
    inputs = demo_inputs(20, NOW)
    inputs["pace_per_day"] = 1e308
    result = analyze(20, inputs, now=NOW)
    assert result["reasons"] == ["count pace and variance are too large for the discrete count model"]


def test_expertise_scores_a_record_without_claiming_skill():
    inputs = demo_inputs(32, NOW)
    result = analyze(32, inputs, now=NOW)
    assert result["analysis"]["brier_score"] == pytest.approx((0.3 ** 2 + 0.4 ** 2) / 2)
    assert "not established expertise" in result["analysis"]["assumption"]
    inputs["calibration_records"][0]["forecast_at"] = inputs["calibration_records"][0]["resolved_at"]
    assert not analyze(32, inputs, now=NOW)["eligible"]


def test_expertise_duplicate_events_are_not_independent_decisions():
    inputs = demo_inputs(32, NOW)
    inputs["calibration_records"][1]["group"] = inputs["calibration_records"][0]["group"]
    assert analyze(32, inputs, now=NOW)["reasons"] == ["calibration IDs and independent groups must be unique"]


def _records(pairs):
    return [{"event_id": f"prior-{i}", "group": f"group-{i}", "probability_yes": p, "outcome_yes": y,
             "forecast_at": NOW - 3 * 86400, "resolved_at": NOW - 86400} for i, (p, y) in enumerate(pairs)]


@pytest.mark.parametrize("pairs,brier", (([(0.95, False), (0.05, True)], 0.9025), ([(0.5, True), (0.5, False)], 0.25)))
def test_expertise_record_no_better_than_always_50_percent_fails(pairs, brier):
    inputs = demo_inputs(32, NOW)
    inputs.update(calibration_records=_records(pairs), min_decisions=2)
    result = analyze(32, inputs, now=NOW)
    assert result["analysis"]["brier_score"] == pytest.approx(brier)
    assert result["eligible"] is False
    assert result["reasons"] == ["calibration record's Brier score is no better than always forecasting 50% (0.25)"]


def test_expertise_record_needs_the_readers_planned_number_of_decisions():
    inputs = demo_inputs(32, NOW)
    inputs["min_decisions"] = 21
    result = analyze(32, inputs, now=NOW)
    assert result["reasons"] == ["calibration record has fewer resolved decisions than min_decisions"]
    del inputs["min_decisions"]
    assert analyze(32, inputs, now=NOW)["reasons"] == ["missing required field: min_decisions"]


@pytest.mark.parametrize("index,field", ((19, "events"), (32, "calibration_records")))
def test_resolved_history_cannot_postdate_evidence_timestamp(index, field):
    inputs = demo_inputs(index, NOW)
    inputs[field][0]["resolved_at"] = NOW - 10
    assert not analyze(index, inputs, now=NOW)["eligible"]


def test_poll_lead_sampling_error_is_not_an_election_probability():
    inputs = demo_inputs(33, NOW)
    inputs["election_model_reviewed"] = False
    result = analyze(33, inputs, now=NOW)
    # No forecast means no pass/fail screen: eligible is null, never true.
    assert result["eligible"] is None and result["reasons"] == []
    assert result["decision_screen"].startswith("none")
    assert "forecast" not in result
    assert result["analysis"]["requires_calibrated_forecast"]
    assert result["analysis"]["vote_share_lead"] == pytest.approx(0.04)
    assert result["analysis"]["lead_standard_error"] == pytest.approx((1.5 * (1 - 0.04 ** 2) / 800) ** 0.5)


@pytest.mark.parametrize("sample,design,points", ((800, 1, 6.6), (800, 1.5, 8.1), (1000, 1, 5.9)))
def test_poll_interval_matches_chapter_17_table_when_shares_leave_undecided_voters(sample, design, points):
    inputs = demo_inputs(33, NOW)
    inputs.update(share_a=0.504, share_b=0.421, sample_size=sample, design_effect=design)
    low, high = analyze(33, inputs, now=NOW)["analysis"]["lead_sampling_interval"]
    assert round(100 * (high - low) / 2, 1) == points


def test_polling_cost_is_included_before_strategy_acceptance():
    inputs = demo_inputs(33, NOW)
    inputs["poll_cost"] = 40
    result = analyze(33, inputs, now=NOW)
    assert not result["eligible"]
    assert result["analysis"]["allocated_poll_cost_per_share"] == 0.4
    assert result["analysis"]["decision"]["edge_per_share"] == pytest.approx(-0.16)


@pytest.mark.parametrize("field,value", (("sample_size", 0), ("share_a", 0.8), ("design_effect", 0.5),
                                         ("planned_shares", 0), ("calibration_notes", "")))
def test_poll_model_validations(field, value):
    inputs = demo_inputs(33, NOW)
    inputs[field] = value
    assert not analyze(33, inputs, now=NOW)["eligible"]


def test_hedge_reduces_scenario_worst_loss_without_claiming_profit():
    inputs = demo_inputs(35, NOW)
    result = analyze(35, inputs, now=NOW)
    assert result["eligible"] and "forecast" not in result
    assert result["analysis"]["premium"] == pytest.approx(180)
    assert result["analysis"]["worst_loss_reduction"] == pytest.approx(320)
    assert result["analysis"]["largest_uncovered_loss"] == 200
    inputs["scenarios"][1]["real_world_loss"] = 2000
    result = analyze(35, inputs, now=NOW)
    assert not result["eligible"]
    assert result["analysis"]["worst_loss_reduction"] == pytest.approx(-180)


@pytest.mark.parametrize("change", ("unaffordable", "no_uncovered_scenarios", "duplicate_scenarios"))
def test_hedge_rejects_incomplete_or_unaffordable_exposure(change):
    inputs = demo_inputs(35, NOW)
    if change == "unaffordable":
        inputs["max_hedge_cost"] = 100
    elif change == "no_uncovered_scenarios":
        for scenario in inputs["scenarios"]:
            scenario["contract_yes"] = True
    else:
        inputs["scenarios"][1]["scenario_id"] = inputs["scenarios"][0]["scenario_id"]
    assert not analyze(35, inputs, now=NOW)["eligible"]


@pytest.mark.parametrize("index", (1, 36, True, "10", float("nan")))
def test_unsupported_model_index(index):
    result = analyze(index, {}, now=NOW)
    assert not result["eligible"]
    json.dumps(result, allow_nan=False)
    with pytest.raises(ValueError):
        demo_inputs(index, NOW)


def test_overflowing_intermediate_does_not_emit_nonfinite_json():
    inputs = demo_inputs(35, NOW)
    inputs.update(hedge_shares=1e308, max_hedge_cost=1e308)
    for scenario in inputs["scenarios"]:
        scenario["real_world_loss"] = 1.7e308
    result = analyze(35, inputs, now=NOW)  # loss plus premium overflows to infinity
    assert not result["eligible"]
    json.dumps(result, allow_nan=False)


def test_the_count_model_refuses_an_expected_count_where_its_sums_lose_accuracy():
    from polymarket_strategies.strategy_models import _count_probability
    # a realistic count agrees with an exact Poisson sum; a huge expected count is refused instead of answered inaccurately
    exact = sum(math.exp(k * math.log(20) - 20 - math.lgamma(k + 1)) for k in range(0, 21))
    assert _count_probability(0, 0, 20, 2.0, 10.0, 1.0) == pytest.approx(exact, abs=1e-12)
    assert _count_probability(0, 99_000, 101_000, 10_000.0, 10.0, 1.0000011) > 0.99  # 100,000 expected: still inside the stated accuracy
    with pytest.raises(ValueError, match="too large"):
        _count_probability(0, 990_000, 1_010_000, 100_000.0, 10.0, 1.0000011)
