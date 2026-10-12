"""Payoff, depth and cost checks on synthetic snapshots; no account or network."""
import json
from copy import deepcopy

import pytest

from polymarket_strategies.strategy_baskets import INDICES, analyze, demo_inputs


NOW = 1_800_000_000


@pytest.mark.parametrize("index", sorted(INDICES))
def test_synthetic_schemas_produce_finite_meaningful_results(index):
    result = analyze(index, demo_inputs(index, NOW), now=NOW)
    assert result["eligible"] and result["analysis"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("index,flag", [(1, "binary_complete_set"), (2, "fixed_outcomes"),
    (3, "implication"), (4, "deadline_nesting"), (5, "void_rules"), (6, "completion_model"),
    (9, "exclusive"), (21, "launch_definition")])
def test_unreviewed_strategy_premise_is_rejected(index, flag):
    data = demo_inputs(index, NOW)
    data["review"][flag] = False
    assert not analyze(index, data, now=NOW)["eligible"]


@pytest.mark.parametrize("index", sorted(INDICES))
@pytest.mark.parametrize("mutation", [
    lambda data: data.update(as_of=NOW - 61),
    lambda data: data.update(valid_until=NOW),
    lambda data: data.update(shares=float("nan")),
    lambda data: data.update(max_cash=0),
    lambda data: data["review"].update(source="true"),
])
def test_bad_or_unfunded_inputs_cannot_pass(index, mutation):
    data = demo_inputs(index, NOW)
    mutation(data)
    result = analyze(index, data, now=NOW)
    assert not result["eligible"] and result["reasons"]
    json.dumps(result, allow_nan=False)


def test_binary_parity_walks_depth_and_every_matched_share_pays():
    data = demo_inputs(1, NOW)
    data["legs"][0]["book"] = [[0.44, 3], [0.46, 7]]
    result = analyze(1, data, now=NOW)
    assert result["eligible"]
    analysis = result["analysis"]
    yes = analysis["legs"][0]
    assert yes["gross_usd"] == pytest.approx(4.54)
    assert [fill["shares"] for fill in yes["fills"]] == [3, 7]
    # Cash fees on top: 0.04 x (3 x 0.44 x 0.56 + 7 x 0.46 x 0.54) = 0.09912, plus 10 x 0.001 slippage.
    assert yes["modeled_fees_usd"] == pytest.approx(0.09912)
    assert yes["modeled_net_usd"] == pytest.approx(4.54 + 0.09912 + 0.01)
    no_cost = 4.8 + 10 * 0.04 * 0.48 * 0.52 + 0.01
    assert analysis["modeled_cost_usd"] == pytest.approx(4.64912 + no_cost)
    assert [row["payout_usd"] for row in analysis["payout_scenarios"]] == pytest.approx([10, 10])
    assert analysis["floor_profit_usd"] == pytest.approx(10 - 4.64912 - no_cost)


def test_incomplete_pair_reports_actual_exposure_instead_of_full_set_payout():
    data = demo_inputs(1, NOW)
    data["legs"][0]["book"] = [[0.45, 2]]
    result = analyze(1, data, now=NOW)
    assert not result["eligible"]
    assert "not enough depth" in result["reasons"][0]
    assert [row["payout_usd"] for row in result["analysis"]["payout_scenarios"]] == pytest.approx([2, 10])
    cost = 2 * (0.45 + 0.04 * 0.45 * 0.55 + 0.001) + 10 * (0.48 + 0.04 * 0.48 * 0.52 + 0.001)
    assert result["analysis"]["floor_profit_usd"] == pytest.approx(2 - cost)


def test_fees_and_slippage_erase_apparent_binary_discount():
    data = demo_inputs(1, NOW)
    data["legs"][0]["book"] = [[0.48, 100]]
    data["legs"][1]["book"] = [[0.51, 100]]
    result = analyze(1, data, now=NOW)
    assert not result["eligible"]
    assert result["reasons"] == ["reviewed payoff floor does not exceed cost plus min_profit"]


def test_buy_fees_are_cash_on_top_so_a_thin_pair_keeps_its_small_floor():
    data = demo_inputs(1, NOW)
    for price, leg in zip((0.45, 0.53), data["legs"]):
        leg.update(book=[[price, 100]], slippage_per_share=0)
    result = analyze(1, data, now=NOW)
    # 10 x (1 - 0.98 - 0.04 x 0.45 x 0.55 - 0.04 x 0.53 x 0.47) = 10 x 0.000136
    assert result["eligible"]
    assert result["analysis"]["floor_profit_usd"] == pytest.approx(0.00136)
    assert [leg["displayed_fill_shares"] for leg in result["analysis"]["legs"]] == [10, 10]


def test_asymmetric_pair_is_a_real_arbitrage_when_fees_are_cash():
    data = demo_inputs(1, NOW)
    for price, leg in zip((0.10, 0.85), data["legs"]):
        leg.update(book=[[price, 100]], slippage_per_share=0)
        leg["fee"]["rate"] = 0.07
    result = analyze(1, data, now=NOW)
    # Per set: 1 - 0.95 - (0.07 x 0.10 x 0.90 + 0.07 x 0.85 x 0.15) = 0.034775, about 3.48 cents.
    assert result["eligible"]
    assert result["analysis"]["floor_profit_usd"] == pytest.approx(10 * 0.034775)


@pytest.mark.parametrize("collection", ["shares_on_buy", None])
def test_fee_collection_must_be_cash(collection):
    data = demo_inputs(1, NOW)
    data["legs"][0]["fee_collection"] = collection
    result = analyze(1, data, now=NOW)
    assert not result["eligible"] and "fee_collection must be cash" in result["reasons"][0]


def _book_legs(template, books, rate, outcomes, ids):
    legs = []
    for book, outcome, market in zip(books, outcomes, ids):
        leg = deepcopy(template)
        leg.update(book=book, outcome=outcome, market_id=market, slippage_per_share=0)
        leg["fee"]["rate"] = rate
        legs.append(leg)
    return legs


def test_chapter_6_parity_toys_match_the_book():
    data = demo_inputs(1, NOW)
    data.update(shares=100, max_cash=1000, legs=_book_legs(data["legs"][0], [[[0.46, 100]], [[0.50, 100]]], 0.05,
                                                          ["YES", "NO"], ["binary", "binary"]))
    # 100 x (0.46 + 0.50) + 100 x 0.05 x (0.46 x 0.54 + 0.25) = 98.492: the book's +$1.51.
    assert analyze(1, data, now=NOW)["analysis"]["floor_profit_usd"] == pytest.approx(1.508)
    data["shares"] = 150
    data["legs"][0]["book"] = [[0.44, 100], [0.46, 200]]
    data["legs"][1]["book"] = [[0.50, 150], [0.52, 300]]
    # YES 100 at 0.44 and 50 at 0.46, NO 150 at 0.50, each plus its cash fee: the book's $4.27 on 150 sets.
    cost = 100 * (0.44 + 0.05 * 0.44 * 0.56) + 50 * (0.46 + 0.05 * 0.46 * 0.54) + 150 * (0.50 + 0.05 * 0.25)
    assert analyze(1, data, now=NOW)["analysis"]["floor_profit_usd"] == pytest.approx(150 - cost)
    assert 150 - cost == pytest.approx(4.272)


def test_chapter_6_four_way_bundle_matches_the_book():
    data = demo_inputs(2, NOW)
    ids = ["a", "b", "c", "d"]
    data.update(shares=100, max_cash=1000, universe=ids,
                legs=_book_legs(data["legs"][0], [[[price, 100]] for price in (0.30, 0.28, 0.25, 0.12)], 0.05, ["YES"] * 4, ids))
    analysis = analyze(2, data, now=NOW)["analysis"]
    # 95 + 5 x (0.21 + 0.2016 + 0.1875 + 0.1056) = 98.5235: the book's $98.52 and +$1.48.
    assert analysis["modeled_cost_usd"] == pytest.approx(98.5235)
    assert analysis["floor_profit_usd"] == pytest.approx(1.4765)


def test_mint_sell_uses_bids_and_models_unsold_inventory():
    data = demo_inputs(1, NOW)
    data.update(mode="mint_sell_set", conversion_cost_usd=0.01)
    data["legs"][0]["book"] = [[0.56, 100]]
    data["legs"][1]["book"] = [[0.50, 100]]
    result = analyze(1, data, now=NOW)
    assert result["eligible"] and result["analysis"]["collateral_required_usd"] == 10.01
    data["legs"][1]["book"] = [[0.50, 4]]
    result = analyze(1, data, now=NOW)
    assert not result["eligible"] and result["analysis"]["unsold_token_shares"] == [0, 6]


@pytest.mark.parametrize("mutation", [
    lambda data: data["legs"].pop(),
    lambda data: data["legs"][1].update(market_id="bucket-a"),
    lambda data: data["legs"][1].update(event_id="different-event"),
    lambda data: data["universe"].append("new-outcome"),
])
def test_negrisk_never_shrinks_or_duplicates_the_event_universe(mutation):
    data = demo_inputs(2, NOW)
    mutation(data)
    assert not analyze(2, data, now=NOW)["eligible"]


def test_negrisk_no_bundle_pays_n_minus_one_not_one():
    data = demo_inputs(2, NOW)
    data["mode"] = "buy_no_bundle"
    for leg in data["legs"]:
        leg["outcome"] = "NO"
        leg["fee"]["rate"] = 0
    result = analyze(2, data, now=NOW)
    assert result["eligible"]
    assert {row["payout_usd"] for row in result["analysis"]["payout_scenarios"]} == {20}


def test_negrisk_conversion_requires_every_other_yes_sale_and_costs():
    data = demo_inputs(2, NOW)
    data.update(mode="convert_no", source_outcome="bucket-a", conversion_cost_usd=0.02)
    data["legs"][0].update(outcome="NO", book=[[0.50, 100]])
    for leg in data["legs"][1:]:
        leg["book"] = [[0.40, 100]]
    result = analyze(2, data, now=NOW)
    assert result["eligible"]
    analysis = result["analysis"]
    assert [leg["action"] for leg in analysis["legs"]] == ["BUY", "SELL", "SELL"]
    # Every bought NO share converts: sell 10 of each other YES at 0.40 less its cash fee and slippage.
    assert [leg["displayed_fill_shares"] for leg in analysis["legs"]] == [10, 10, 10]
    capital = 10 * (0.50 + 0.04 * 0.25 + 0.001) + 0.02
    proceeds = 2 * 10 * (0.40 - 0.04 * 0.40 * 0.60 - 0.001)
    assert analysis["cash_required_usd"] == pytest.approx(capital)
    assert analysis["modeled_profit_usd"] == pytest.approx(proceeds - capital)
    data["conversion_cost_usd"] = 4
    result = analyze(2, data, now=NOW)
    assert not result["eligible"] and result["reasons"] == ["conversion profit does not exceed min_profit"]


def test_logical_pair_includes_middle_double_payout_and_excludes_only_reviewed_impossibility():
    result = analyze(3, demo_inputs(3, NOW), now=NOW)
    assert result["eligible"]
    assert [row["payout_usd"] for row in result["analysis"]["payout_scenarios"]] == pytest.approx([10, 20, 10])
    cost = 10 * (0.28 + 0.04 * 0.28 * 0.72 + 0.001) + 10 * (0.68 + 0.04 * 0.68 * 0.32 + 0.001)
    assert result["analysis"]["floor_profit_usd"] == pytest.approx(10 - cost)
    data = demo_inputs(3, NOW)
    data["implication_evidence"] = ""
    result = analyze(3, data, now=NOW)
    assert not result["eligible"] and result["reasons"] == ["implication_evidence must be nonempty text"]


@pytest.mark.parametrize("index,no_price,per_set", [(3, 0.68, 0.023232), (4, 0.69, 0.01338)])
def test_chapter_7_implication_and_ladder_toys_match_the_book(index, no_price, per_set):
    data = demo_inputs(index, NOW)
    data.update(shares=100, max_cash=1000)
    for leg, price in zip(data["legs"], (0.28, no_price)):
        leg.update(book=[[price, 100]], slippage_per_share=0)
    analysis = analyze(index, data, now=NOW)["analysis"]
    # 1 - 0.28 - no_price - 0.04 x (0.28 x 0.72 + no_price x (1 - no_price)): 2.32 and 1.34 cents a set in the book.
    assert analysis["floor_profit_usd"] == pytest.approx(100 * per_set)
    assert max(row["profit_usd"] for row in analysis["payout_scenarios"]) == pytest.approx(100 + 100 * per_set)


def test_date_nesting_is_directional_and_source_specific():
    data = demo_inputs(4, NOW)
    data["legs"][1]["cutoff"] = data["legs"][0]["cutoff"] + 1
    assert analyze(4, data, now=NOW)["reasons"] == ["earlier cutoff must precede later cutoff"]
    data = demo_inputs(4, NOW)
    data["legs"][1]["source"] = "https://example.com/different"
    assert analyze(4, data, now=NOW)["reasons"] == ["contracts do not match on source"]


@pytest.mark.parametrize("subject", [None, "", "different-underlying-event"])
def test_date_ladder_requires_same_explicit_underlying_event(subject):
    data = demo_inputs(4, NOW)
    data["legs"][1]["underlying_event_id"] = subject
    result = analyze(4, data, now=NOW)
    assert not result["eligible"] and "underlying_event_id" in result["reasons"][0]


def test_date_ladder_rungs_differ_in_definition_and_the_definitions_are_reported():
    data = demo_inputs(4, NOW)
    data["legs"][0]["definition"] = "X happens by 31 December"
    data["legs"][1]["definition"] = "X happens by 30 June"
    result = analyze(4, data, now=NOW)
    assert result["eligible"], result["reasons"]
    assert result["analysis"]["leg_definitions"] == ["X happens by 31 December", "X happens by 30 June"]


def test_date_ladder_can_span_distinct_gamma_events_with_reviewed_common_subject():
    data = demo_inputs(4, NOW)
    data["legs"][1]["event_id"] = "different-gamma-date-event"
    assert analyze(4, data, now=NOW)["eligible"]
    data["legs"][1]["underlying_event_id"] = "unrelated-event-with-similar-wording"
    assert not analyze(4, data, now=NOW)["eligible"]


def test_crossvenue_agreeing_profit_never_hides_harmful_double_loss():
    data = demo_inputs(5, NOW)
    result = analyze(5, data, now=NOW)
    assert result["eligible"]
    analysis = result["analysis"]
    assert analysis["matched_resolution_floor_profit_usd"] > 0
    assert analysis["floor_profit_usd"] == -analysis["modeled_cost_usd"]
    data["harmful_mismatch_probability_upper"] = 0.10
    result = analyze(5, data, now=NOW)
    assert result["reasons"] == ["conservative mismatch-adjusted profit does not exceed min_profit"]


# Demo legs: 10 shares, YES 0.55 and NO 0.38, both rate 0.04 cash fees and 0.001 slippage, 0.01 transfer cost,
# 4% a year funding for 35 days.
A5_COST = (10 * (0.55 + 0.04 * 0.55 * 0.45 + 0.001) + 10 * (0.38 + 0.04 * 0.38 * 0.62 + 0.001) + 0.01) * (1 + 0.04 * 35 / 365)


def test_crossvenue_counts_every_legs_cash_fee_when_the_other_venue_payout_binds():
    data = demo_inputs(5, NOW)
    data["legs"][1]["payout_usd_floor"] = 0.98
    data["min_profit"] = 0.20
    result = analyze(5, data, now=NOW)
    # 0.99 x 9.8 - 9.5598 = 0.1422; leaving the Polymarket leg's fee out of cost would show 0.2416 and pass.
    assert result["analysis"]["conservative_expected_profit_usd"] == pytest.approx(0.99 * 9.8 - A5_COST)
    assert result["reasons"] == ["conservative mismatch-adjusted profit does not exceed min_profit"]


def test_crossvenue_beneficial_mismatch_is_removed_from_the_matched_weight():
    data = demo_inputs(5, NOW)
    data["beneficial_mismatch_probability_lower"] = 0.05
    result = analyze(5, data, now=NOW)
    # (1 - 0.01 - 0.05) x 10 + 0.05 x 20 = 10.4 expected payout.
    assert result["analysis"]["conservative_expected_profit_usd"] == pytest.approx(10.4 - A5_COST)


def test_crossvenue_funding_horizon_flat_fees_and_currency_floor_matter():
    data = demo_inputs(5, NOW)
    data["maximum_lock_days"] = 800
    assert not analyze(5, data, now=NOW)["eligible"]
    data = demo_inputs(5, NOW)
    data["legs"][1]["fee"]["flat_per_share"] = 0.08
    assert not analyze(5, data, now=NOW)["eligible"]
    data = demo_inputs(5, NOW)
    data["legs"][0]["payout_usd_floor"] = 2
    assert not analyze(5, data, now=NOW)["eligible"]


def test_legged_inventory_allocates_paired_cost_and_keeps_orphan_exposure():
    data = demo_inputs(6, NOW)
    result = analyze(6, data, now=NOW)
    analysis = result["analysis"]
    assert result["eligible"]
    assert analysis["observed_paired_shares"] == 5
    assert analysis["observed_paired_cost_usd"] == pytest.approx(4.75)
    assert analysis["observed_pair_payout_profit_usd"] == pytest.approx(0.25)
    assert analysis["unpaired_yes_shares"] == 2
    assert analysis["unpaired_acquisition_cost_usd"] == pytest.approx(0.92)
    assert analysis["break_even_completion_probability"] == pytest.approx(0.1 / 0.148)
    data["completion_probability_lower"] = 0.6
    assert not analyze(6, data, now=NOW)["eligible"]


def test_legged_full_loss_cap_and_unknown_maker_fees_block_screen():
    data = demo_inputs(6, NOW)
    data["max_stranded_loss_usd"] = 4
    assert not analyze(6, data, now=NOW)["eligible"]
    data = demo_inputs(6, NOW)
    data["legs"][0]["fee"]["taker_only"] = False
    assert not analyze(6, data, now=NOW)["eligible"]


def test_tail_ladder_is_one_coverage_bet_with_an_outside_zero_payout():
    data = demo_inputs(9, NOW)
    result = analyze(9, data, now=NOW)
    assert result["eligible"]
    rows = result["analysis"]["payout_scenarios"]
    assert rows[-1]["ending"] == "middle" and rows[-1]["payout_usd"] == 0
    assert result["analysis"]["maximum_loss_usd"] == result["analysis"]["modeled_cost_usd"]
    data["coverage_probability_lower"] = 0.05
    assert not analyze(9, data, now=NOW)["eligible"]


def test_tail_missing_depth_cannot_invent_full_coverage_expected_profit():
    data = demo_inputs(9, NOW)
    data["legs"][0]["book"] = [[0.02, 2]]
    result = analyze(9, data, now=NOW)
    assert not result["eligible"]
    assert result["analysis"]["conservative_expected_profit_usd"] is None


def test_chapter_8_tail_ladder_toy_matches_the_book():
    data = demo_inputs(9, NOW)
    ids = ["a", "b", "c", "d", "e", "rest"]
    data.update(shares=1, universe=ids, coverage_probability_lower=0.25,
                legs=_book_legs(data["legs"][0], [[[price, 100]] for price in (0.02, 0.03, 0.04, 0.05, 0.08)], 0.05, ["YES"] * 5, ids[:5]))
    for leg in data["legs"]:
        leg["min_size"] = 1
    result = analyze(9, data, now=NOW)
    # 0.22 + 0.05 x (0.0196 + 0.0291 + 0.0384 + 0.0475 + 0.0736) = 0.23041: the book's 23.04 cents and 23.04%.
    assert result["analysis"]["break_even_coverage_probability"] == pytest.approx(0.23041)
    assert result["analysis"]["conservative_expected_profit_usd"] == pytest.approx(0.25 - 0.23041)
    assert result["eligible"]


def test_fdv_probability_multiplies_launch_and_conditional_value():
    data = demo_inputs(21, NOW)
    result = analyze(21, data, now=NOW)
    assert result["eligible"]
    rung = result["analysis"]["rung_values"][0]
    assert rung["joint_probability"] == pytest.approx(0.54)
    assert rung["conservative_joint_probability"] == pytest.approx(0.4)
    assert rung["no_launch_profit_usd"] == -rung["modeled_cost_usd"]
    data.update(launch_probability=0, launch_probability_lower=0)
    assert not analyze(21, data, now=NOW)["eligible"]


def test_fdv_higher_bar_cannot_have_greater_probability():
    data = demo_inputs(21, NOW)
    data["rungs"][1]["conditional_probability"] = 0.95
    assert not analyze(21, data, now=NOW)["eligible"]


@pytest.mark.parametrize("key,value", [("launch_id", None), ("launch_id", ""),
    ("launch_id", "different-token-launch"), ("event_id", None), ("event_id", "unrelated-launch-event")])
def test_fdv_rejects_false_launch_universes_even_when_source_definition_and_flags_match(key, value):
    data = demo_inputs(21, NOW)
    data["rungs"][1]["leg"][key] = value
    result = analyze(21, data, now=NOW)
    assert not result["eligible"] and result["reasons"]
    assert result["analysis"] == {}


def test_fdv_book_example_loses_the_books_0065_cents_a_pair_after_fees():
    data = demo_inputs(21, NOW)
    data.update(launch_probability=0.2, launch_probability_lower=0.1)
    data["rungs"][0]["leg"]["book"] = [[0.17, 100]]
    data["rungs"][1]["no_book"] = [[0.81, 100]]
    for rung in data["rungs"]:
        rung["leg"]["fee"]["rate"] = 0.07
        rung["leg"]["slippage_per_share"] = 0
    result = analyze(21, data, now=NOW)
    pair = result["analysis"]["nested_pairs"][0]
    assert pair["reasons"] == ["nested FDV pair does not cover its cost above min_profit"]
    # Per pair: 1 - 0.98 - 0.07 x (0.17 x 0.83 + 0.81 x 0.19) = -0.00065, Chapter 12's "loses 0.065 cents".
    assert pair["floor_profit_usd"] == pytest.approx(10 * -0.00065)
    assert result["reasons"] == ["no funded-depth rung value or nested pair passes the modeled screen"]


def test_fdv_rungs_differ_in_definition_and_report_it():
    data = demo_inputs(21, NOW)
    result = analyze(21, data, now=NOW)
    assert result["eligible"], result["reasons"]
    assert [rung["definition"] for rung in result["analysis"]["rung_values"]] == [
        "Synthetic token FDV above $100M one day after launch", "Synthetic token FDV above $500M one day after launch"]


def test_fdv_checks_nonadjacent_pairs_as_well_as_neighboring_rungs():
    data = demo_inputs(21, NOW)
    middle = deepcopy(data["rungs"][0])
    middle.update(threshold_usd=300_000_000, conditional_probability=0.7, conditional_probability_lower=0.6,
                  no_book=[[0.99, 100]])
    middle["leg"].update(market_id="middle", book=[[0.9, 100]])
    data["rungs"].insert(1, middle)
    data["rungs"][0]["leg"]["book"] = [[0.1, 100]]
    data["rungs"][2]["no_book"] = [[0.6, 100]]
    result = analyze(21, data, now=NOW)
    pairs = result["analysis"]["nested_pairs"]
    assert len(pairs) == 3
    assert pairs[1]["eligible"] and not pairs[0]["eligible"] and not pairs[2]["eligible"]


@pytest.mark.parametrize("mutation", [
    lambda data: data["legs"][0].update(as_of=NOW - 61),
    lambda data: data["legs"][0].update(book=[[0.45, float("inf")]]),
    lambda data: data["legs"][0].update(book=[[0.5, 10], [0.4, 10]]),
    lambda data: data["legs"][0].update(fee=None),
    lambda data: data["legs"][0].update(usd_per_unit=0.5),
])
def test_leg_boundary_rejects_stale_unknown_fee_bad_depth_or_wrong_currency(mutation):
    data = demo_inputs(1, NOW)
    mutation(data)
    assert not analyze(1, data, now=NOW)["eligible"]


@pytest.mark.parametrize("index,mutation", [
    (1, lambda data: data.update(legs=[[], []])),
    (21, lambda data: data["rungs"].__setitem__(0, "rung")),
    (21, lambda data: data["rungs"][0].update(leg=["not", "an", "object"])),
    (6, lambda data: data.update(inventory=[7, 5])),
])
def test_wrong_containers_are_reported_as_named_input_errors(index, mutation):
    data = demo_inputs(index, NOW)
    mutation(data)
    result = analyze(index, data, now=NOW)
    assert not result["eligible"] and "object" in result["reasons"][0]
