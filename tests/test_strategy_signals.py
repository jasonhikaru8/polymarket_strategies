"""Money, timing, source and observation boundaries for the indexed signal tools."""
import copy
import math

import pytest

from polymarket_strategies.strategy_signals import SUPPORTED, analyze, demo_inputs


NOW = 1_700_000_000
FORECASTS = {15, 16, 17, 18, 25, 34}


@pytest.mark.parametrize("index", SUPPORTED)
def test_complete_synthetic_schema_passes_with_correct_output_scope(index):
    result = analyze(index, demo_inputs(index, NOW), now=NOW)
    # Strategy 26 is a monitor with no pass/fail screen, so it reports null rather than true.
    assert result["eligible"] is (None if index == 26 else True), result["reasons"]
    assert bool(result.get("forecast")) == (index in FORECASTS)


@pytest.mark.parametrize("index", SUPPORTED)
@pytest.mark.parametrize("change", ["expired", "future", "source", "definition", "nonfinite"])
def test_all_tools_reject_expired_future_mismatched_or_nonfinite_envelopes(index, change):
    inputs = demo_inputs(index, NOW)
    if change == "expired":
        inputs["valid_until"] = NOW
    elif change == "future":
        inputs["as_of"] = NOW + 1
    elif change == "source":
        inputs["contract"]["resolution_source"] = "Another official source"
    elif change == "definition":
        inputs["contract"]["yes_definition"] = "Another contract outcome"
    else:
        inputs["fee_per_share"] = math.nan
    result = analyze(index, inputs, now=NOW)
    assert not result["eligible"]
    assert result["reasons"]
    assert "forecast" not in result


@pytest.mark.parametrize("index,field,value,reason", [
    (15, "report_matches_contract_reviewed", False, "report_matches_contract_reviewed must be explicitly true"),
    (16, "conservative_high_yes", .99, "conservative edge after the entry fee is below min_edge"),
    (17, "benchmark_fixed_at", NOW - 10, "benchmark must precede release"),
    (18, "min_rate_ratio", 4, "attention growth is below min_rate_ratio"),
    (22, "execution_latency_seconds", 10, "exhaust the opportunity window"),
    (23, "sports_order_delay_seconds", 10, "exhaust the opportunity window"),
    (24, "planned_exit_bid", .51, "planned round-trip edge after fees and slippage is below min_edge"),
    (25, "contract_status", "disputed", "restricted to open, non-resolution markets"),
    (26, "phase", "unknown", "unknown resolution phase"),
    (27, "inventory", 49, "proposal exceeds inventory capacity"),
    (28, "rewards_eligible", False, "rewards_eligible must be explicitly true"),
    (29, "settlement_rules_match", False, "settlement_rules_match must be explicitly true"),
    (30, "max_copy_price_premium", .001, "follower cost premium exceeds the preselected threshold"),
    (31, "min_notional_usdc", 1000, "observed flow does not meet every preselected alert threshold"),
    (34, "duty_restricted", True, "requires no duty restriction or outcome influence"),
])
def test_each_strategy_has_a_meaningful_negative_case(index, field, value, reason):
    inputs = demo_inputs(index, NOW)
    inputs[field] = value
    result = analyze(index, inputs, now=NOW)
    assert result["eligible"] is False, result
    assert any(reason in text for text in result["reasons"]), result["reasons"]
    assert "forecast" not in result


@pytest.mark.parametrize("index", sorted(FORECASTS))
def test_forecast_probabilities_are_reader_supplied_and_bounds_are_enforced(index):
    inputs = demo_inputs(index, NOW)
    inputs["conservative_low_yes"] = .9
    result = analyze(index, inputs, now=NOW)
    assert not result["eligible"]
    assert "forecast" not in result


@pytest.mark.parametrize("index", (15, 25, 34))
def test_public_evidence_provenance_and_publication_clock_are_checked(index):
    inputs = demo_inputs(index, NOW)
    report = inputs["source_document" if index == 25 else "report"]
    report["published_at"] = report["received_at"] + 1
    result = analyze(index, inputs, now=NOW)
    assert not result["eligible"]
    assert "receipt cannot precede" in result["reasons"][0]


@pytest.mark.parametrize("field,value", [("archive_sha256", "wrong"), ("publicly_accessible", False),
                                         ("provenance_reviewed", False), ("url", "private://document")])
def test_public_report_does_not_accept_unreviewed_private_or_unarchived_sources(field, value):
    inputs = demo_inputs(34, NOW)
    inputs["report"][field] = value
    assert not analyze(34, inputs, now=NOW)["eligible"]


def test_news_forecast_cannot_claim_to_include_a_later_received_report():
    inputs = demo_inputs(15, NOW)
    inputs["report"]["received_at"] = NOW
    assert not analyze(15, inputs, now=NOW)["eligible"]


def test_fade_resolution_probability_is_not_rumor_confidence():
    inputs = demo_inputs(16, NOW)
    result = analyze(16, inputs, now=NOW)
    assert result["forecast"]["probability_yes"] == .4
    assert result["analysis"]["implied_rumor_confidence_under_two_state_assumption"] == pytest.approx(2 / 3)
    assert result["analysis"]["decision"]["conservative_probability"] == .5


def test_fade_exit_mark_prices_two_fees_without_producing_a_contract_forecast():
    inputs = demo_inputs(16, NOW)
    inputs.update(mode="exit_mark", rumor_confirmation_probability=.25, exit_yes_if_confirmed=1,
                  exit_yes_if_denied=.4, exit_fee_if_confirmed=.01, exit_fee_if_denied=.01,
                  slippage_reserve=.005)
    result = analyze(16, inputs, now=NOW)
    assert result["eligible"], result
    assert result["analysis"]["expected_exit_mark"] == pytest.approx(.45)
    assert result["analysis"]["expected_profit_per_share"] == pytest.approx(.225)
    assert "forecast" not in result


def test_macro_reports_surprise_and_requires_independent_contract_forecast():
    inputs = demo_inputs(17, NOW)
    result = analyze(17, inputs, now=NOW)
    assert result["analysis"]["standardized_surprise"] == 2
    assert result["forecast"]["probability_yes"] == .75
    del inputs["probability_yes"]
    assert not analyze(17, inputs, now=NOW)["eligible"]


def test_attention_adjusts_for_window_duration_and_does_not_turn_counts_into_probability():
    inputs = demo_inputs(18, NOW)
    result = analyze(18, inputs, now=NOW)
    assert result["analysis"]["rate_ratio"] == 3
    assert result["forecast"]["probability_yes"] == .75
    inputs["current_period"]["start"] -= 60
    assert not analyze(18, inputs, now=NOW)["eligible"]  # overlapping windows


def test_attention_zero_baseline_cannot_produce_an_infinite_growth_signal():
    inputs = demo_inputs(18, NOW)
    inputs["baseline_period"]["count"] = 0
    result = analyze(18, inputs, now=NOW)
    assert not result["eligible"]
    assert result["analysis"]["rate_ratio"] is None
    assert "forecast" not in result


@pytest.mark.parametrize("index", (22, 23))
def test_latency_requires_fresh_quotes_and_correct_reference(index):
    inputs = demo_inputs(index, NOW)
    inputs["quote_at"] = NOW - 20
    assert not analyze(index, inputs, now=NOW)["eligible"]
    inputs = demo_inputs(index, NOW)
    inputs["reference_matches_contract"] = False
    assert not analyze(index, inputs, now=NOW)["eligible"]


def test_sports_delay_is_additional_to_submission_latency_and_clock_uncertainty():
    inputs = demo_inputs(23, NOW)
    inputs["opportunity_expires_at"] = NOW + 3
    result = analyze(23, inputs, now=NOW)
    assert not result["eligible"]
    assert result["analysis"]["earliest_match_delay_seconds"] == 3.25


def test_scalp_costs_both_fees_and_slippage_and_preserves_exit_uncertainty():
    result = analyze(24, demo_inputs(24, NOW), now=NOW)
    assert result["analysis"]["planned_profit_per_share"] == pytest.approx(.035)
    assert result["analysis"]["planned_profit_usdc"] == pytest.approx(.35)
    assert "forecast" not in result


@pytest.mark.parametrize("index,field", [(22, "opportunity_expires_at"), (24, "exit_deadline")])
def test_exit_or_latency_scenario_cannot_extend_beyond_contract_deadline(index, field):
    inputs = demo_inputs(index, NOW)
    inputs["contract"]["end_time"] = NOW + 2
    inputs[field] = NOW + 3
    assert not analyze(index, inputs, now=NOW)["eligible"]


@pytest.mark.parametrize("field", ("source_match", "timezone", "units", "cutoff", "ties", "exceptions"))
def test_rules_reject_an_unreviewed_contract_exception(field):
    inputs = demo_inputs(25, NOW)
    inputs["rule_review"][field] = False
    assert not analyze(25, inputs, now=NOW)["eligible"]


def test_dispute_monitor_does_not_turn_a_proposal_into_a_forecast_or_guaranteed_winner():
    inputs = demo_inputs(26, NOW)
    inputs["contract"]["end_time"] = NOW - 300
    result = analyze(26, inputs, now=NOW)
    assert result["eligible"] is None and result["reasons"] == []
    assert result["decision_screen"].startswith("none")
    assert result["analysis"]["challenge_open"]
    assert result["analysis"]["monitor_alert"]
    assert "forecast" not in result
    inputs["phase"] = "disputed"
    assert not analyze(26, inputs, now=NOW)["analysis"]["challenge_open"]


@pytest.mark.parametrize("phase", ("open", "proposed", "disputed", "voting", "resolved"))
def test_dispute_monitor_is_never_reported_as_an_eligible_screen(phase):
    inputs = demo_inputs(26, NOW)
    inputs["phase"] = phase
    if phase == "open":
        inputs.update(proposal_at=None, challenge_deadline=None)
    assert analyze(26, inputs, now=NOW)["eligible"] is None


def test_inventory_quotes_shift_down_and_account_for_two_fees_and_adverse_selection():
    result = analyze(27, demo_inputs(27, NOW), now=NOW)
    analysis = result["analysis"]
    assert analysis["inventory_shift"] == pytest.approx(-.01)
    assert analysis["bid_proposal"]["price"] == .42
    assert analysis["ask_proposal"]["price"] == .56
    assert analysis["round_trip_margin"] == pytest.approx(.10)
    assert "forecast" not in result


def test_quote_grid_uses_decimal_before_rounding_and_never_creates_a_short_position():
    inputs = demo_inputs(27, NOW)
    inputs.update(inventory=10, target_inventory=10, half_spread=.05)
    result = analyze(27, inputs, now=NOW)
    assert result["analysis"]["bid_proposal"]["price"] == .45
    assert result["analysis"]["ask_proposal"]["price"] == .55
    inputs["ask_size"] = 11
    assert not analyze(27, inputs, now=NOW)["eligible"]


def test_sportsbook_devig_uses_each_sides_odds():
    inputs = demo_inputs(29, NOW)
    inputs.update(yes_decimal_odds=1.50, no_decimal_odds=2.80)
    analysis = analyze(29, inputs, now=NOW)["analysis"]
    # (1 / 1.50) / (1 / 1.50 + 1 / 2.80) = 2.80 / 4.30
    assert analysis["no_vig_probability_yes"] == pytest.approx(2.80 / 4.30)
    assert analysis["sportsbook_overround"] == pytest.approx(1 / 1.50 + 1 / 2.80 - 1)
    assert analysis["fair_outcome_probability"] == pytest.approx(2.80 / 4.30)


def test_reward_score_uses_program_spread_units_and_cash_remains_conditional():
    result = analyze(28, demo_inputs(28, NOW), now=NOW)
    analysis = result["analysis"]
    assert analysis["account_min_score"] == pytest.approx(40 / 9)
    assert analysis["conditional_pool_share_usdc"] == pytest.approx(40 / 9)
    assert "not period-normalized" in analysis["limitation"]
    assert "forecast" not in result


def test_reward_single_sided_quote_fails_at_extreme_midpoints():
    inputs = demo_inputs(28, NOW)
    inputs["orders"] = inputs["orders"][:1]
    inputs["size_adjusted_midpoint"] = .05
    assert not analyze(28, inputs, now=NOW)["eligible"]
    inputs["size_adjusted_midpoint"] = .5
    result = analyze(28, inputs, now=NOW)
    assert result["analysis"]["account_min_score"] == pytest.approx(40 / 27)


@pytest.mark.parametrize("change", ("size", "spread", "total", "duplicate"))
def test_reward_ineligible_orders_and_invalid_total_pool_score_fail_closed(change):
    inputs = demo_inputs(28, NOW)
    if change == "size":
        inputs["orders"][0]["size"] = 1
    elif change == "spread":
        inputs["orders"][0]["spread_cents"] = 3
    elif change == "total":
        inputs["snapshot_total_min_score"] = 1
    else:
        inputs["orders"][1]["id"] = inputs["orders"][0]["id"]
    assert not analyze(28, inputs, now=NOW)["eligible"]


def test_sportsbook_removes_proportional_vig_without_claiming_an_independent_forecast():
    inputs = demo_inputs(29, NOW)
    result = analyze(29, inputs, now=NOW)
    assert result["analysis"]["no_vig_probability_yes"] == .5
    assert result["analysis"]["sportsbook_overround"] == pytest.approx(2 / 1.91 - 1)
    assert "forecast" not in result
    inputs["sportsbook_probability_uncertainty"] = .1
    assert not analyze(29, inputs, now=NOW)["eligible"]


def test_copy_audit_includes_open_losses_and_separates_copyability_from_skill():
    inputs = demo_inputs(30, NOW)
    result = analyze(30, inputs, now=NOW)
    assert result["analysis"]["training_audit"]["net_pnl"] == 3
    assert result["analysis"]["training_audit"]["distinct_events"] == 1
    assert result["analysis"]["follower_cost_premium_per_share"] == pytest.approx(.02)
    assert "forecast" not in result
    inputs["open_and_closed_positions_included"] = False
    assert not analyze(30, inputs, now=NOW)["eligible"]


@pytest.mark.parametrize("change", ("duplicate", "future_training", "late_selection", "false_complete"))
def test_copy_histories_reject_duplicates_future_selection_leakage_and_missing_losses(change):
    inputs = demo_inputs(30, NOW)
    if change == "duplicate":
        inputs["training_trades"].append(copy.deepcopy(inputs["training_trades"][0]))
    elif change == "future_training":
        inputs["training_positions"][0]["observed_at"] = NOW - 60
    elif change == "late_selection":
        inputs["selection_fixed_at"] = NOW - 30
    else:
        inputs["history_complete_reviewed"] = False
    assert not analyze(30, inputs, now=NOW)["eligible"]


@pytest.mark.parametrize("change", ("duplicate", "future", "before_created", "stale"))
def test_flow_history_rejects_duplicate_future_impossible_or_out_of_window_records(change):
    inputs = demo_inputs(31, NOW)
    if change == "duplicate":
        inputs["trades"][1]["id"] = inputs["trades"][0]["id"]
    elif change == "future":
        inputs["trades"][1]["timestamp"] = NOW + 1
    elif change == "before_created":
        inputs["wallet_created_at"] = NOW - 450
    else:
        inputs["lookback_seconds"] = 300
    assert not analyze(31, inputs, now=NOW)["eligible"]


def test_flow_alert_is_not_an_insider_label_or_probability():
    result = analyze(31, demo_inputs(31, NOW), now=NOW)
    assert result["analysis"]["anomaly_alert"]
    assert result["analysis"]["observed_notional_usdc"] == 400
    assert "does not identify an insider" in result["analysis"]["limitation"]
    assert "forecast" not in result


def test_overflow_is_rejected_without_returning_infinite_derived_analysis():
    inputs = demo_inputs(31, NOW)
    for trade in inputs["trades"]:
        trade.update(size=1e308, price=.99, cash_notional_usdc=.99e308)
    result = analyze(31, inputs, now=NOW)
    assert result["reasons"] == ["flow notional must be positive and finite"]
    assert result["analysis"] == {}


@pytest.mark.parametrize("index,record", [(30, "target_trade"), (30, "training_trades"), (31, "trades")])
def test_wallet_cash_in_cents_or_base_units_is_rejected(index, record):
    inputs = demo_inputs(index, NOW)
    row = inputs[record] if record == "target_trade" else inputs[record][0]
    row["cash_notional_usdc"] *= 100
    result = analyze(index, inputs, now=NOW)
    assert result["eligible"] is False
    assert "cash_notional_usdc must be the trade's dollars" in result["reasons"][0]


def test_copy_premium_in_cents_cannot_turn_a_rejected_copy_into_a_pass():
    inputs = demo_inputs(30, NOW)
    inputs["limit_price"] = .60
    result = analyze(30, inputs, now=NOW)
    # 0.60 + 0.01 fee - 4.90 / 10 = 0.12 premium, above the 0.03 threshold.
    assert result["analysis"]["follower_cost_premium_per_share"] == pytest.approx(.12)
    assert result["reasons"] == ["follower cost premium exceeds the preselected threshold"]
    inputs["target_trade"]["cash_notional_usdc"] = 490
    assert analyze(30, inputs, now=NOW)["eligible"] is False


@pytest.mark.parametrize("index", (True, 15.0, 99))
def test_index_is_a_known_integer_not_a_boolean_or_rounded_float(index):
    assert not analyze(index, {}, now=NOW)["eligible"]


def test_missing_inputs_are_actionable_and_do_not_mutate_caller_data():
    inputs = demo_inputs(25, NOW)
    original = copy.deepcopy(inputs)
    analyze(25, inputs, now=NOW)
    assert inputs == original
    del inputs["rule_review"]["exceptions"]
    result = analyze(25, inputs, now=NOW)
    assert result["reasons"] == ["missing required field: exceptions"]


@pytest.mark.parametrize("second_outcome,second_side", [("NO", "BUY"), ("YES", "SELL")])
def test_opposite_outcomes_and_round_trips_do_not_look_like_directional_wallet_flow(second_outcome, second_side):
    inputs = demo_inputs(31, NOW)
    second = inputs["trades"][1]
    second.update(condition_id="condition-1", event="event-1", outcome=second_outcome, side=second_side)
    result = analyze(31, inputs, now=NOW)
    assert not result["eligible"]
    assert not result["analysis"]["anomaly_alert"]
    assert result["analysis"]["dominant_direction_share"] == 0
    assert result["analysis"]["net_positive_share_change"] == 0
    assert result["analysis"]["net_negative_share_change"] == 0


def test_binary_yes_labels_require_reviewed_economic_mapping_across_conditions():
    inputs = demo_inputs(31, NOW)
    inputs["condition_mappings"][1]["yes_direction"] = "NEGATIVE"
    result = analyze(31, inputs, now=NOW)
    assert not result["eligible"]
    assert result["analysis"]["dominant_direction_share"] == .5
    assert result["analysis"]["net_positive_share_change"] == 400
    assert result["analysis"]["net_negative_share_change"] == 400


def test_sell_no_and_buy_yes_have_the_same_binary_exposure_direction():
    inputs = demo_inputs(31, NOW)
    inputs["trades"][1].update(condition_id="condition-1", event="event-1", outcome="NO", side="SELL")
    result = analyze(31, inputs, now=NOW)
    assert result["eligible"]
    assert result["analysis"]["dominant_direction_share"] == 1
    assert result["analysis"]["net_positive_share_change"] == 800


@pytest.mark.parametrize("change", ("unreviewed", "unmapped", "wrong_event", "duplicate_mapping", "wrong_wallet"))
def test_flow_requires_one_wallet_and_exact_reviewed_condition_event_mapping(change):
    inputs = demo_inputs(31, NOW)
    if change == "unreviewed":
        inputs["condition_mappings"][0]["reviewed"] = False
    elif change == "unmapped":
        inputs["trades"][0]["condition_id"] = "another-condition"
    elif change == "wrong_event":
        inputs["trades"][0]["event"] = "another-event"
    elif change == "duplicate_mapping":
        inputs["condition_mappings"].append(copy.deepcopy(inputs["condition_mappings"][0]))
    else:
        inputs["trades"][0]["wallet"] = "Synthetic Wallet B"
    result = analyze(31, inputs, now=NOW)
    assert not result["eligible"]
    assert result["reasons"]


@pytest.mark.parametrize("record", ("target_trade", "training_trades", "training_positions"))
def test_copy_cannot_mix_selected_wallet_a_history_with_wallet_b_records(record):
    inputs = demo_inputs(30, NOW)
    row = inputs[record] if record == "target_trade" else inputs[record][0]
    row["wallet"] = "Synthetic Wallet B"
    result = analyze(30, inputs, now=NOW)
    assert not result["eligible"]
    assert "selected_wallet" in result["reasons"][0]


@pytest.mark.parametrize("change", ("target_market", "target_event", "context_market", "context_event", "unreviewed"))
def test_copy_cannot_bind_identical_prose_and_source_to_a_different_market_or_event(change):
    inputs = demo_inputs(30, NOW)
    if change == "target_market":
        inputs["target_trade"]["market_id"] = "another-market"
    elif change == "target_event":
        inputs["target_trade"]["event"] = "another-event"
    elif change == "context_market":
        inputs["contract"]["market_id"] = "another-market"
    elif change == "context_event":
        inputs["contract"]["event_id"] = "another-event"
    else:
        inputs["target_identity_reviewed"] = False
    assert not analyze(30, inputs, now=NOW)["eligible"]


def test_copy_cash_weighting_and_cost_premium_use_actual_cash_including_the_buy_fee():
    inputs = demo_inputs(30, NOW)
    inputs["training_trades"][0]["cash_notional_usdc"] = 4.1  # 10 x 0.40 plus a 1-cent fee a share
    inputs["target_trade"]["cash_notional_usdc"] = 5.0  # 10 x 0.49 plus a 1-cent fee a share
    result = analyze(30, inputs, now=NOW)
    assert result["eligible"]
    assert result["analysis"]["training_audit"]["buy_dollars"] == 4.1
    assert result["analysis"]["target_actual_cost_per_share"] == .5
    assert result["analysis"]["follower_cost_premium_per_share"] == pytest.approx(.50 + .01 - .5)


def test_scalp_entry_fee_is_cash_on_top_and_every_matched_share_counts():
    inputs = demo_inputs(24, NOW)
    inputs["fee_per_share"] = .04 * .5 * .5  # rate 0.04 at the 0.50 entry
    result = analyze(24, inputs, now=NOW)
    assert result["analysis"]["planned_profit_per_share"] == pytest.approx(.56 - .5 - .01 - .01 - .005)
    assert result["analysis"]["planned_profit_usdc"] == pytest.approx(10 * .035)


def test_reward_scoring_uses_the_resting_order_size():
    inputs = demo_inputs(28, NOW)
    inputs["orders"][0]["size"] = 5
    result = analyze(28, inputs, now=NOW)
    assert result["eligible"]
    # One side scores ((3 - 1) / 3) ** 2 x 5 = 20 / 9, the other 40 / 9; two-sided quoting takes the smaller.
    assert result["analysis"]["account_min_score"] == pytest.approx(20 / 9)
