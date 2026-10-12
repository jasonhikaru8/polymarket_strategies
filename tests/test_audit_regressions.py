"""Regressions for the reader-code review: no network or account credentials."""
import json
from types import SimpleNamespace as NS

import pytest

from polymarket_strategies import baskets, crypto_pricing, edge_check, fees, journal


@pytest.mark.parametrize("enabled", [True, None, "false"])
def test_unknown_fee_metadata_is_not_free_trading(enabled):
    with pytest.raises(ValueError):
        fees.schedule_from_market(NS(trading=NS(fees_enabled=enabled, fee_schedule=None)))


def test_explicitly_disabled_fees_and_valid_schedule():
    assert fees.schedule_from_market(NS(trading=NS(fees_enabled=False))).rate == 0
    schedule = NS(rate=.07, exponent=1, rebate_rate=.2, taker_only=True)
    assert fees.schedule_from_market(NS(trading=NS(fees_enabled=True, fee_schedule=schedule))) == fees.FeeSchedule(.07, 1, .2)
    with pytest.raises(ValueError):
        fees.schedule_from_market(NS(trading=NS(fee_schedule=schedule)))
    with pytest.raises(ValueError):
        fees.schedule_from_market(NS())


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), -.01])
def test_bad_market_fee_parameters_are_rejected(rate):
    schedule = NS(rate=rate, exponent=1, rebate_rate=.2, taker_only=True)
    with pytest.raises(ValueError):
        fees.schedule_from_market(NS(trading=NS(fees_enabled=True, fee_schedule=schedule)))


def test_up_barrier_already_reached_and_ordinary_probabilities():
    assert crypto_pricing.touch_probability(120, 110, .5, 30) == 1
    assert crypto_pricing.touch_probability(110, 110, .5, 30) == 1
    assert crypto_pricing.digital_probability(100_000, 110_000, .5, 30) == pytest.approx(.230691678)
    assert crypto_pricing.touch_probability(100_000, 110_000, .5, 30) == pytest.approx(.482069118)
    assert crypto_pricing.digital_probability(100, 100, 0, 30) == 0  # strictly above
    assert crypto_pricing.touch_probability(100, 110, 0, 30) == 0


@pytest.mark.parametrize("args", [(0, 110, .5, 30), (100, -110, .5, 30),
                                  (100, 110, -.5, 30), (100, 110, .5, -30),
                                  (float("nan"), 110, .5, 30)])
def test_probability_models_reject_invalid_domains(args):
    for calculate in (crypto_pricing.digital_probability, crypto_pricing.touch_probability):
        with pytest.raises(ValueError):
            calculate(*args)


def test_implied_vol_must_reproduce_its_target():
    target = crypto_pricing.touch_probability(100, 110, .5, 30)
    assert crypto_pricing.implied_touch_vol(target, 100, 110, 30) == pytest.approx(.5)
    for args in [(.95, 100, 110, 30), (0, 100, 110, 30),
                 (float("nan"), 100, 110, 30), (1, 120, 110, 30)]:
        with pytest.raises(ValueError):
            crypto_pricing.implied_touch_vol(*args)


def test_twap_known_outcomes_and_zero_variance_award_ties_to_up():
    assert crypto_pricing.twap_up_probability(60 * 101, 101, 0, .02, 100) == 1
    assert crypto_pricing.twap_up_probability(60 * 99, 99, 0, .02, 100) == 0
    assert crypto_pricing.twap_up_probability(60 * 100, 100, 0, .02, 100) == 1
    assert crypto_pricing.twap_up_probability(40 * 100, 100, 20, 0, 100) == 1
    assert crypto_pricing.twap_up_probability(40 * 100, 99, 20, 0, 100) == 0
    assert crypto_pricing.twap_up_probability(40 * 100, 99.98, 20, .02, 100) == pytest.approx(.354452655)
    assert crypto_pricing.twap_disagreement(300, 60) == {"correlation": .9333, "disagree": .1169}


@pytest.mark.parametrize("seconds,sigma,window", [(-1, .02, 60), (61, .02, 60),
                                                (20, -.02, 60), (20, float("nan"), 60),
                                                (0, .02, 0)])
def test_twap_rejects_invalid_window_inputs(seconds, sigma, window):
    with pytest.raises(ValueError):
        crypto_pricing.twap_up_probability(4000, 100, seconds, sigma, 100, window)


@pytest.mark.parametrize("step", [.3, .6, 1])
def test_blend_grid_includes_one_without_extrapolation(step):
    fit = edge_check.best_blend([.9, .1], [.5, .5], [1, 0], step=step)
    assert fit["weight_on_model"] == 1
    assert fit["blend_log_loss"] == pytest.approx(fit["model_log_loss"])


@pytest.mark.parametrize("step", [0, -1, 1.1, float("nan"), float("inf")])
def test_blend_rejects_invalid_steps(step):
    with pytest.raises(ValueError):
        edge_check.best_blend([.9], [.5], [1], step=step)


@pytest.mark.parametrize("prob", [float("nan"), -.1, 1.1])
def test_forecast_scores_do_not_hide_bad_probabilities(prob):
    for score in (edge_check.log_loss, edge_check.brier):
        with pytest.raises(ValueError):
            score([prob], [1])


def test_minimum_size_basket_can_cross_an_unprofitable_marginal_level():
    free = fees.FeeSchedule(0)
    result = baskets.walk([[(.4, 3), (.55, 2)], [(.5, 5)]],
                          baskets.buy_basket_profit([free, free]), min_size=5)
    assert result["sets"] == 5 and result["placeable"] is True
    assert result["profit"] == pytest.approx(.2)  # $4.80 spent, $5 received
    assert result["steps"][-1]["profit_per_set"] < 0
    losing = baskets.walk([[(.4, 3), (.8, 20)], [(.5, 20)]],
                          baskets.buy_basket_profit([free, free]), min_size=5)
    assert losing["sets"] == 5 and losing["profit"] < 0 and losing["placeable"] is False


def test_breakeven_minimum_basket_is_not_profitable_due_to_roundoff():
    result = baskets.walk([[(.4, 3), (.65, 2)], [(.5, 5)]],
                          baskets.buy_basket_profit([fees.FeeSchedule(0)] * 2), min_size=5)
    assert result["sets"] == 5 and result["profit"] == pytest.approx(0)
    assert result["placeable"] is False


@pytest.mark.parametrize("size", [-1, 0, float("nan"), float("inf")])
def test_invalid_depth_cannot_create_a_placeable_basket(size):
    with pytest.raises(ValueError):
        baskets.walk([[(.4, size)], [(.5, 5)]], baskets.buy_basket_profit([fees.FeeSchedule(0)] * 2))


@pytest.mark.parametrize("overrides", [{"shares": -1}, {"fee": -1}, {"ask": 0},
                                      {"shares": float("nan")}, {"fee": float("inf")},
                                      {"model_prob": 1.1}, {"group": ""}])
def test_journal_rejects_impossible_decisions_before_appending(tmp_path, overrides):
    path = tmp_path / "paper.jsonl"
    fields = {"strategy": "C8", "market": "example", "group": "event", "ask": .5, "shares": 10}
    with pytest.raises(ValueError):
        journal.log_decision(path, **(fields | overrides))
    assert not path.exists()


@pytest.mark.parametrize("won", ["false", 0, 1, None])
def test_journal_requires_boolean_outcomes(tmp_path, won):
    path = tmp_path / "paper.jsonl"
    with pytest.raises(ValueError):
        journal.log_outcome(path, "decision", won)
    assert not path.exists()


@pytest.mark.parametrize("bad_shares", [-10, float("nan")])
def test_manually_corrupted_journal_cannot_produce_evidence(tmp_path, bad_shares):
    path = tmp_path / "paper.jsonl"
    decision = journal.log_decision(path, strategy="x", market="m", group="g", ask=.5, shares=10)
    journal.log_outcome(path, decision, False)
    lines = path.read_text().splitlines()
    row = json.loads(lines[0])
    row["shares"] = bad_shares
    path.write_text(json.dumps(row) + "\n" + lines[1] + "\n")
    with pytest.raises(ValueError):
        journal.summarize(path)


def test_loaded_journal_rejects_nonboolean_outcomes_and_rewritten_decisions(tmp_path):
    path = tmp_path / "paper.jsonl"
    decision = journal.log_decision(path, strategy="x", market="m", group="g", ask=.5, shares=10)
    journal.log_outcome(path, decision, False)
    lines = path.read_text().splitlines()
    row = json.loads(lines[1])
    row["won"] = "false"
    path.write_text(lines[0] + "\n" + json.dumps(row) + "\n")
    with pytest.raises(ValueError):
        journal.summarize(path)
    path.write_text(lines[0] + "\n" + lines[0] + "\n" + lines[1] + "\n")
    with pytest.raises(ValueError):
        journal.summarize(path)


@pytest.mark.parametrize("n", [5, 19, 20, 23, 31, 46])
@pytest.mark.parametrize("said", [False, True])
def test_a_word_never_said_or_always_said_is_a_valid_history_for_strategy_19(n, said):
    """These lengths used to fail on round-off (0 of 20 gave a lower bound of -1.4e-17) and the error named a field the reader never wrote."""
    from polymarket_strategies import strategy_catalog as catalog
    now = 1_800_000_000
    inputs = catalog.example(19, now=now)
    template = inputs["events"][0]
    inputs["events"] = [{**template, "event_id": f"e{i}", "group": f"g{i}", "outcome_yes": said} for i in range(n)]
    inputs.update(min_events=min(inputs["min_events"], n), outcome="YES" if said else "NO", limit_price=0.5 if said else 0.7)
    result = catalog.analyze(19, inputs, now=now)
    assert not any("permitted range" in reason for reason in result["reasons"])  # the error that round-off used to cause
    assert result["eligible"] or n < 19, result["reasons"]  # 19 or more events leave an edge at these prices; with five the interval may be too wide


def test_a_dip_market_uses_the_lower_barrier_formula_and_never_exceeds_one():
    """The up formula gave 1.62 for a $90,000 dip with spot $100,000; the lower-barrier value is 0.4868."""
    assert crypto_pricing.touch_probability(100_000, 90_000, .5, 30, direction="down") == pytest.approx(.4868, abs=5e-5)
    assert crypto_pricing.touch_probability(100_000, 60_000, .5, 30, direction="down") < .05
    for strike in range(10_000, 100_000, 5_000):
        p = crypto_pricing.touch_probability(100_000, strike, .8, 90, direction="down")
        assert 0 < p < 1
    assert crypto_pricing.touch_probability(100, 110, .5, 30, direction="down") == 1  # already at or below the strike
    assert crypto_pricing.touch_probability(100, 90, 0, 30, direction="down") == 0


def test_the_direction_must_be_named_correctly_and_implied_vol_works_for_a_dip():
    with pytest.raises(ValueError, match="direction"):
        crypto_pricing.touch_probability(100, 110, .5, 30, direction="sideways")
    target = crypto_pricing.touch_probability(100_000, 90_000, .5, 30, direction="down")
    assert crypto_pricing.implied_touch_vol(target, 100_000, 90_000, 30, direction="down") == pytest.approx(.5)
    with pytest.raises(ValueError):
        crypto_pricing.implied_touch_vol(.2, 100_000, 90_000, 30)  # the default "up" cannot read a barrier below the spot
