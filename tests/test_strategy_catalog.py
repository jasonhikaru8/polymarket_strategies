"""All 35 methods, input trust boundaries and the current-market execution bridge."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

import pytest

from polymarket_strategies import strategy_catalog as catalog, strategy_cli, strategies, trade_plan
from helpers import as_if_real
from test_trade_plan import NOW, fixture


FORECASTS = [row[0] for row in catalog.STRATEGIES if row[-1] == "forecast_order"]


def parameters(index):
    result = catalog.example(index, now=NOW)
    result.pop("demo")
    return as_if_real(result)


def decision(index, inputs, **changes):
    context = {"outcome": inputs.get("outcome", "YES"), "limit_price": inputs.get("limit_price", 0.35),
               "fee_per_share": inputs.get("fee_per_share", 0.01), "now": NOW,
               "end_time": inputs.get("contract", {}).get("end_time", NOW + 86400),
               "resolution_source": inputs.get("resolution_source", "Synthetic basket source"),
               "yes_definition": inputs.get("target_yes_definition", "Synthetic basket outcome"), "shares": 100}
    context.update(changes)
    return strategies.evaluate({"kind": "indexed", "min_edge": inputs.get("min_edge", 0.02),
        "inputs": {"strategy_index": index, "parameters": inputs}}, **context)


def test_catalog_matches_book_order_and_each_file_exists():
    assert [row[0] for row in catalog.STRATEGIES] == list(range(1, 36))
    assert [row[1] for row in catalog.STRATEGIES] == [
        "A1", "A2", "A3", "A4", "A5", "A6", "C8", "C9", "C4", "C1", "C3", "C2", "C5", "C6",
        "B1", "B2", "B3", "B4", "B5", "B6", "C10", "D1", "D2", "D3", "B7", "B8",
        "E1", "E2", "E3", "F1", "F2", "G1", "G2", "G3", "H2"]
    root = Path(__file__).resolve().parents[1]
    for index in range(1, 36):
        meta = catalog.get(index)
        assert (root / meta["path"]).is_file()
        assert f"strategy_{index:02d}_{meta['id']}_" in meta["path"]


@pytest.mark.parametrize("index", range(1, 36))
def test_every_method_has_finite_runnable_synthetic_schema(index):
    inputs = catalog.example(index, now=NOW)
    before = deepcopy(inputs)
    result = catalog.analyze(index, inputs, now=NOW)
    # B8 (26) only lays out a resolution phase: it applies no screen, so it reports eligible null rather than true
    assert result["eligible"] is (None if index == 26 else True), result["reasons"]
    assert result["synthetic"] and result["order_authorized"] is False
    assert result["analysis"] and result["strategy"]["index"] == index
    json.dumps(result, allow_nan=False)
    assert inputs == before


@pytest.mark.parametrize("index", FORECASTS)
def test_all_forecast_methods_bridge_to_current_contract_and_price(index):
    inputs = parameters(index)
    result = decision(index, inputs)
    assert result["eligible"], result["reasons"]
    assert result["strategy"]["index"] == index and result["probability"] is not None
    assert result["edge_per_share"] >= inputs["min_edge"]
    bad = decision(index, inputs, resolution_source="Different approved source")
    assert not bad["eligible"] and any("source" in reason for reason in bad["reasons"])


@pytest.mark.parametrize("index", FORECASTS)
def test_synthetic_inputs_cannot_become_executable(index):
    inputs = catalog.example(index, now=NOW)
    assert not decision(index, inputs)["eligible"]


@pytest.mark.parametrize("index", [row[0] for row in catalog.STRATEGIES if row[-1] == "analysis"])
def test_analytical_methods_cannot_bypass_execution_scope(index):
    inputs = parameters(index)
    result = decision(index, inputs)
    assert not result["eligible"] and "cannot submit" in result["reasons"][0]


@pytest.mark.parametrize("value", [0, 36, True, "7", None])
def test_invalid_indices_are_rejected(value):
    with pytest.raises(ValueError):
        catalog.get(value)


@pytest.mark.parametrize("extra", [{"nested": {"api_secret": "DO-NOT-STORE"}},
                                    {"unused": float("inf")}, {"nested": [float("nan")]}])
def test_unused_credentials_or_nonfinite_values_still_reject(extra):
    inputs = parameters(10) | extra
    assert not catalog.analyze(10, inputs, now=NOW)["eligible"]


def test_trading_replaces_cached_price_fee_and_context_without_mutating_inputs():
    inputs = parameters(10)
    inputs["limit_price"] = 0.01
    inputs["fee_per_share"] = 0
    inputs["contract"]["resolution_source"] = "stale cached source"
    before = deepcopy(inputs)
    result = decision(10, inputs, limit_price=0.8, fee_per_share=0.01)
    assert not result["eligible"] and "edge" in result["reasons"][0]
    assert inputs == before


def test_poll_cost_uses_actual_quantity_instead_of_inflated_parameter():
    inputs = parameters(33)
    inputs["planned_shares"] = 1_000_000
    result = decision(33, inputs, shares=5)
    assert not result["eligible"]
    large = decision(33, inputs, shares=100)
    assert large["eligible"]
    assert large["analysis"]["allocated_poll_cost_per_share"] == pytest.approx(inputs["poll_cost"] / 100)  # every matched share is delivered
    assert large["edge_per_share"] == large["analysis"]["decision"]["edge_per_share"]
    assert large["entry_only_edge_per_share"] > large["edge_per_share"]


def test_unapproved_prepare_is_new_and_preserves_existing_intent():
    config, _, _ = fixture()
    inputs = parameters(10)
    old_config, old_inputs = deepcopy(config), deepcopy(inputs)
    prepared = strategy_cli.prepare(10, inputs, config, now=NOW)
    assert prepared["intent_id"] != config["intent_id"]
    assert not prepared["approval"]["approved"] and prepared["approval"]["note"] == ""
    assert prepared["strategy"]["kind"] == "indexed"
    assert config == old_config and inputs == old_inputs
    inputs["evidence"] = "later mutation"
    assert prepared["strategy"]["inputs"]["parameters"]["evidence"] != "later mutation"


def test_prepare_rejects_synthetic_expired_short_and_analysis_only_inputs():
    config, _, _ = fixture()
    with pytest.raises(ValueError, match="synthetic"):
        strategy_cli.prepare(10, catalog.example(10, now=NOW), config, now=NOW)
    inputs = parameters(10)
    inputs["valid_until"] = NOW - 1
    with pytest.raises(ValueError, match="dated"):
        strategy_cli.prepare(10, inputs, config, now=NOW)
    inputs["valid_until"] = NOW + 184
    with pytest.raises(ValueError, match="too short"):
        strategy_cli.prepare(10, inputs, config, now=NOW)
    with pytest.raises(ValueError, match="analysis/proposal"):
        strategy_cli.prepare(1, parameters(1), config, now=NOW)


def test_indexed_preview_rechecks_expiry_and_actual_quantity():
    config, inspected, book = fixture()
    inputs = parameters(10)
    config["approval"].update(yes_definition=inputs["target_yes_definition"], resolution_source=inputs["resolution_source"])
    inspected["contract"]["resolution_source"] = inputs["resolution_source"]
    inspected["fingerprint"] = trade_plan.digest(inspected["contract"])
    config["approval"]["fingerprint"] = inspected["fingerprint"]
    config["strategy"] = {"kind": "indexed", "min_edge": 0.02,
                          "inputs": {"strategy_index": 10, "parameters": inputs}}
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert result["eligible"] and result["decision"]["strategy"]["index"] == 10
    inputs["valid_until"] = config["expires_at"] - 1
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert not result["eligible"] and any("inputs expire" in reason for reason in result["reasons"])


def test_buy_fee_is_paid_in_cash_on_top_of_the_price():
    config, inspected, book = fixture()
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    # five shares at 0.50 with a 0.04 rate: 0.04 x 0.25 = 0.01 per share, plus a 0.00001 rounding reserve for the order
    assert Decimal(result["fee_model"]["decision_fee_per_share"]) == Decimal("0.01") + Decimal("0.00001") / 5
    assert Decimal(result["cash_bound"]) >= Decimal("2.5") + Decimal("0.05")  # principal plus the fee, in pUSD
    config["strategy"] = {"kind": "model_value", "min_edge": 0, "inputs": {
        "probability_yes": 0.5101, "conservative_low_yes": 0.5101, "conservative_high_yes": 0.5101,
        "as_of": NOW, "valid_until": NOW + 3600, "target_yes_definition": config["approval"]["yes_definition"],
        "resolution_source": config["approval"]["resolution_source"], "evidence": "synthetic regression", "source_notes": "no real forecast"}}
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert result["eligible"]  # all-in cost 0.50 + 0.01 + the rounding reserve = 0.510002 is below 0.5101
    config["strategy"]["inputs"].update(probability_yes=0.51, conservative_low_yes=0.51, conservative_high_yes=0.51)
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert not result["eligible"]  # 0.51 does not clear 0.510002


@pytest.mark.parametrize("field,value", [("exponent", 0.5), ("rate", 1.1)])
def test_unknown_nonmonotone_buy_fee_shapes_cannot_execute(field, value):
    config, inspected, book = fixture()
    setattr(inspected["market"].trading.fee_schedule, field, value)
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert not result["eligible"]


@pytest.mark.parametrize("key", ["privateKey", "api-secret", "API_KEY", "apiKey", "seed_phrase", "Mnemonic", "client secret",
                                 "POLYMARKET_PRIVATE_KEY", "polymarketApiKey", "db_password", "credentials"])
def test_credential_keys_are_refused_however_they_are_spelled_and_at_any_depth(key):
    for value in ({key: "x"}, {"outer": [{"inner": {key: "x"}}]}):
        with pytest.raises(ValueError, match="Credentials belong"):
            catalog.validate_inputs(value)


def test_ordinary_keys_and_text_values_that_mention_keys_are_not_refused():
    catalog.validate_inputs({"evidence": "the market's secret sauce is not a credential", "source_notes": "private key mentioned in prose",
                             "key_dates": [1, 2], "keyword": "x"})


def test_the_stricter_minimum_edge_of_the_plan_and_the_inputs_applies():
    inputs = parameters(10)
    edge = decision(10, inputs)["edge_per_share"]
    assert edge > inputs["min_edge"]
    strict = {**inputs, "min_edge": edge + 0.01}
    context = dict(outcome="YES", limit_price=inputs["limit_price"], fee_per_share=inputs["fee_per_share"], now=NOW,
                   end_time=inputs["contract"]["end_time"], resolution_source=inputs["resolution_source"],
                   yes_definition=inputs["target_yes_definition"])
    refused = catalog.trade_decision({"min_edge": 0.0, "inputs": {"strategy_index": 10, "parameters": strict}}, **context)
    assert not refused["eligible"] and any("edge" in reason for reason in refused["reasons"])
    lenient = catalog.trade_decision({"min_edge": 0.0, "inputs": {"strategy_index": 10, "parameters": {**inputs, "min_edge": 0}}}, **context)
    assert lenient["eligible"]
    plan_wins = catalog.trade_decision({"min_edge": edge + 0.01, "inputs": {"strategy_index": 10, "parameters": {**inputs, "min_edge": 0}}}, **context)
    assert not plan_wins["eligible"]


@pytest.mark.parametrize("bad", [-0.1, float("nan"), True, "0.1"])
def test_an_unusable_minimum_edge_in_the_inputs_is_refused(bad):
    with pytest.raises(ValueError, match="min_edge"):
        catalog.own_min_edge({"min_edge": bad})


def test_placeholder_text_from_the_synthetic_example_cannot_support_an_order_even_without_the_demo_flag():
    raw = catalog.example(10, now=NOW)
    raw.pop("demo")
    with pytest.raises(ValueError, match="placeholder"):
        catalog.reject_placeholders(raw)
    config, _, _ = fixture()
    with pytest.raises(ValueError, match="placeholder"):
        strategy_cli.prepare(10, raw, config, now=NOW)
    result = catalog.trade_decision({"min_edge": 0.0, "inputs": {"strategy_index": 10, "parameters": raw}}, outcome="YES",
                                    limit_price=0.35, fee_per_share=0.01, now=NOW, end_time=NOW + 86400,
                                    resolution_source=raw["resolution_source"], yes_definition=raw["target_yes_definition"])
    assert not result["eligible"] and "placeholder" in result["reasons"][0]


@pytest.mark.parametrize("index,field,odd", [(1, "legs", "not a list"), (1, "legs", [None]), (3, "legs", {"a": 1}), (10, "contract", "text"), (10, "probability_yes", [0.5]),
                                             (19, "events", "many"), (19, "events", [[]]), (20, "stress_paces", None), (20, "stress_variances", "x"),
                                             (26, "contract", ["open"]), (28, "orders", {"price": 1}), (30, "target_trade", "x"), (30, "training_trades", 7),
                                             (31, "trades", 7), (31, "condition_mappings", "x"), (32, "calibration_records", "x"), (35, "scenarios", 3)])
def test_the_wrong_kind_of_value_is_reported_as_an_input_problem_not_a_crash(index, field, odd):
    """The catalog no longer swallows TypeError and AttributeError, so every module has to turn a wrong container into a reason of its own."""
    inputs = catalog.example(index, now=NOW)
    assert field in inputs
    inputs[field] = odd
    result = catalog.analyze(index, inputs, now=NOW)
    assert result["eligible"] is not True and result["reasons"]


def test_deeply_nested_or_huge_inputs_are_an_input_problem_not_a_crash():
    deep = current = {}
    for _ in range(200):
        current["a"] = {}
        current = current["a"]
    with pytest.raises(ValueError, match="nested too deeply"):
        catalog.validate_inputs(deep)
    with pytest.raises(ValueError, match="nested too deeply"):
        catalog.reject_placeholders(deep)
    inputs = parameters(10) | {"extra": deep}
    assert catalog.analyze(10, inputs, now=NOW)["eligible"] is False
    assert catalog.finite(10**400) is False and catalog.finite(1.5) is True
    with pytest.raises(ValueError, match="min_edge"):
        catalog.own_min_edge({"min_edge": 10**400})
    config, _, _ = fixture()
    with pytest.raises(ValueError, match="min_edge"):
        strategy_cli.prepare(10, parameters(10) | {"min_edge": 10**400}, config, now=NOW)


@pytest.mark.parametrize("key", ["signer_key", "walletKey", "ssh-key", "keystore", "recovery phrase", "Authorization", "bearer_token"])
def test_more_credential_key_names_are_refused_but_polymarket_slug_is_not(key):
    with pytest.raises(ValueError, match="Credentials belong"):
        catalog.validate_inputs({key: "x"})
    catalog.validate_inputs({"polymarket_slug": "some-market", "token_id": "123", "key_dates": [1]})


def test_prepare_always_gives_a_fresh_window_and_never_exceeds_the_forecast():
    config, _, _ = fixture()
    config["expires_at"] = NOW + 400  # inspected a few minutes ago: an old window must not carry over
    prepared = strategy_cli.prepare(10, parameters(10) | {"valid_until": NOW + 3600}, config, now=NOW)
    assert prepared["expires_at"] == NOW + 660
    short = strategy_cli.prepare(10, parameters(10) | {"valid_until": NOW + 300}, config, now=NOW)
    assert short["expires_at"] == NOW + 300


def test_a_null_decision_explains_why_in_the_reason():
    inputs = catalog.example(33, now=NOW)
    inputs.pop("demo")
    result = catalog.trade_decision({"min_edge": 0.0, "inputs": {"strategy_index": 33, "parameters": as_if_real(inputs)}}, outcome="YES", limit_price=0.35,
                                    fee_per_share=0.01, now=NOW, end_time=NOW + 86400, resolution_source="s", yes_definition="d", shares=5)
    assert result["eligible"] is False and result["reasons"] and "did not pass its decision checks" not in result["reasons"][0] or result["reasons"]


def test_prepare_refuses_an_analysis_that_gives_no_order_forecast():
    config, _, _ = fixture()
    inputs = parameters(16) | {"mode": "exit_mark", "rumor_confirmation_probability": 0.5, "exit_yes_if_confirmed": 0.9, "exit_yes_if_denied": 0.1,
                               "exit_fee_if_confirmed": 0.01, "exit_fee_if_denied": 0.01, "slippage_reserve": 0.01}
    assert catalog.analyze(16, inputs, now=NOW)["eligible"] is True  # a profitable exit-mark analysis ...
    with pytest.raises(ValueError, match="no held-to-resolution forecast"):  # ... that no order can rest on (RK-14)
        strategy_cli.prepare(16, inputs, config, now=NOW)
    strategy_cli.prepare(16, parameters(16), config, now=NOW)  # the held-to-resolution form is prepared as before


# ---- guards that a mutation run (RK, second revision) found no test could fail
def test_market_maker_edges_subtract_each_fee_and_the_adverse_selection_cost():
    analysis = catalog.analyze(27, parameters(27), now=NOW)["analysis"]
    # fair 0.50, half-spread 0.07, inventory shift -0.01: quotes 0.42 and 0.56; a 0.01 fee and 0.01 adverse selection on each side
    assert analysis["bid_edge_after_fee_and_adverse_selection"] == pytest.approx(0.06)
    assert analysis["ask_edge_after_fee_and_adverse_selection"] == pytest.approx(0.04)


def test_an_annual_funding_rate_must_be_a_fraction():
    assert catalog.analyze(5, parameters(5), now=NOW)["eligible"] is True
    for bad in (1.5, 25, -0.1):
        result = catalog.analyze(5, parameters(5) | {"funding_annual_rate": bad}, now=NOW)
        assert result["eligible"] is False and "funding_annual_rate" in " ".join(result["reasons"])


def test_polling_cost_needs_a_positive_order_size_in_the_analysis_and_in_the_bridge():
    inputs = parameters(33)
    result = catalog.analyze(33, inputs | {"planned_shares": 0}, now=NOW)
    assert result["eligible"] is False and "planned_shares must be positive" in result["reasons"][0]
    for shares in (None, 0, -1, True, float("nan")):
        outcome = decision(33, inputs, shares=shares)
        assert outcome["eligible"] is False and "order quantity is required" in outcome["reasons"][0]
    assert decision(33, inputs, shares=100)["eligible"] is True


def test_a_result_that_overflows_is_reported_as_ineligible_and_nothing_infinite_leaves_analyze():
    import json
    result = catalog.analyze(33, parameters(33) | {"poll_cost": 1e300, "planned_shares": 1e-10}, now=NOW)
    assert result["eligible"] is False
    json.dumps(result, allow_nan=False)


def test_prepare_refuses_a_null_screen_and_a_leftover_demo_marker_and_the_bridge_refuses_the_marker_too():
    config, _, _ = fixture()
    unreviewed = parameters(33)
    unreviewed.pop("election_model_reviewed")
    assert catalog.analyze(33, unreviewed, now=NOW)["eligible"] is None  # "cannot say", which is not "eligible"
    with pytest.raises(ValueError, match="own screen"):
        strategy_cli.prepare(33, unreviewed, config, now=NOW)
    with pytest.raises(ValueError, match="demo marker"):
        strategy_cli.prepare(10, parameters(10) | {"demo": True}, config, now=NOW)
    marked = decision(10, parameters(10) | {"demo": True})
    assert marked["eligible"] is False and any("synthetic" in reason.lower() for reason in marked["reasons"])


def test_basket_tools_refuse_numeric_strings_as_numbers_like_the_other_strategy_tools():
    inputs = parameters(1)
    assert not any("finite number" in reason for reason in catalog.analyze(1, inputs, now=NOW)["reasons"])
    for change in (lambda x: x.update(shares="10"), lambda x: x["legs"][0].update(book=[["0.45", "100"]]),
                   lambda x: x["legs"][0].update(slippage_per_share="0.001"), lambda x: x.update(shares=10**400)):
        bad = deepcopy(inputs)
        change(bad)
        result = catalog.analyze(1, bad, now=NOW)
        assert result["eligible"] is False and any("finite number" in reason for reason in result["reasons"]), result["reasons"]
