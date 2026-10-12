"""Calculators are checked against numbers printed in Polymarket's own docs (verified 2026-09-29)."""
import json
import math
from pathlib import Path

import pytest

from polymarket_strategies import carry, edge_check, fees, journal, reward_score, safety, sizing


# ---- fees: docs.polymarket.com/trading/fees (fee table for 100 shares) ----
@pytest.mark.parametrize("category,price,expected", [
    ("crypto", 0.50, 1.75), ("crypto", 0.30, 1.47), ("crypto", 0.05, 0.3325), ("crypto", 0.99, 0.0693),
    ("sports", 0.50, 1.25), ("sports", 0.25, 0.94),
    ("politics", 0.50, 1.00), ("finance", 0.50, 1.00),
    ("weather", 0.50, 1.25), ("geopolitics", 0.50, 0.0),
])
def test_taker_fee_matches_docs_table(category, price, expected):
    assert fees.taker_fee(100, price, fees.schedule_for(category)) == pytest.approx(expected, abs=0.006)


def test_fee_is_symmetric_around_half():
    s = fees.schedule_for("crypto")
    assert fees.taker_fee(100, 0.30, s) == fees.taker_fee(100, 0.70, s)


def test_fee_fraction_of_cost_at_95c():
    assert fees.fee_fraction_of_cost(0.95, fees.schedule_for("crypto")) == pytest.approx(0.0035)
    assert fees.fee_fraction_of_cost(0.95, fees.schedule_for("politics")) == pytest.approx(0.0020)


def test_taker_rebate_weighted_volume_examples_from_docs():
    assert fees.weighted_volume(400, 0.40, "politics") == pytest.approx(312.0)       # docs example 1
    assert fees.weighted_volume(50, 0.50, "crypto") == pytest.approx(57.5)           # docs example 2
    assert fees.weighted_volume(50, 0.05, "crypto") == pytest.approx(109.25)


def test_tier_lookup():
    assert fees.tier_for(1_999) == ("None", 0.0)
    assert fees.tier_for(2_000) == ("Bronze", 0.03)
    assert fees.tier_for(10_000_000) == ("Obsidian", 0.50)


# ---- sizing ----
def test_kelly_even_odds():
    assert sizing.kelly_fraction(0.6, 0.5) == pytest.approx(0.2)


def test_kelly_is_zero_without_edge_and_smaller_with_fees():
    assert sizing.kelly_fraction(0.5, 0.5) == 0.0
    assert sizing.kelly_fraction(0.6, 0.5, fee_per_share=0.0175) < sizing.kelly_fraction(0.6, 0.5)


def test_fractional_kelly_is_capped():
    assert sizing.fractional_kelly(0.8) == 0.05
    assert sizing.fractional_kelly(0.1) == pytest.approx(0.025)


def test_cluster_cap_scales_linked_bets():
    out = sizing.cap_clusters({"a": 0.03, "b": 0.03, "c": 0.02}, {"a": "e1", "b": "e1", "c": "e2"}, 0.04)
    assert out["a"] + out["b"] == pytest.approx(0.04) and out["c"] == 0.02


def test_martingale_numbers_from_the_book():
    assert sizing.martingale_exposure(10, 6) == (630, 640)
    assert sizing.expected_trades_to_losing_streak(7, 0.5) == pytest.approx(254)


# ---- carry ----
def test_one_loss_cancels_32_wins_at_97c():
    assert carry.wins_needed_per_loss(0.97) == pytest.approx(32.33, abs=0.01)


def test_annualized_carry():
    assert carry.annualized(0.01, 365) == pytest.approx(0.01)
    assert carry.annualized(0.01, 60) > 0.06


def test_holding_reward_matches_help_center_example():
    hourly = carry.holding_reward_hourly(30_000, 0.53, 10_000, 0.45)  # help article shows about 0.0757
    assert hourly == pytest.approx(0.075697, rel=1e-3)


# ---- reward score: docs worked example (max spread 3c, midpoint 0.50) ----
def test_reward_score_worked_example():
    q_one = reward_score.side_score(3, [(1, 100), (2, 200), (1, 100)])
    q_two = reward_score.side_score(3, [(1.5, 100), (2, 100), (0.5, 200)])
    assert q_one == pytest.approx(111.11, abs=0.01) and q_two == pytest.approx(175.0, abs=0.01)
    assert reward_score.min_score(q_one, q_two, 0.50) == pytest.approx(111.11, abs=0.01)


def test_single_sided_only_scores_inside_the_band():
    assert reward_score.min_score(90, 0, 0.50) == pytest.approx(30)
    assert reward_score.min_score(90, 0, 0.95) == 0
    assert reward_score.order_score(3, 3.0) == 0


# ---- edge check ----
def test_log_loss_prefers_the_better_forecast():
    y = [1, 0, 1, 1]
    assert edge_check.log_loss([0.9, 0.1, 0.8, 0.9], y) < edge_check.log_loss([0.6, 0.4, 0.6, 0.6], y)
    assert edge_check.brier([1, 0], [1, 0]) == 0


def test_bootstrap_counts_linked_trades_once():
    mean, lo, hi = edge_check.bootstrap_mean([1, 1, 1, 1], groups=["e1", "e1", "e2", "e2"])
    assert mean == pytest.approx(2.0) and lo <= mean <= hi


def test_simulated_trades_pay_the_fee():
    s = fees.schedule_for("weather")
    trades = edge_check.simulate_taker_trades([{"model_prob": 0.70, "ask": 0.50, "outcome": 0}], s)
    assert len(trades) == 1 and trades[0]["pnl"] == pytest.approx(-(0.50 + fees.fee_per_share(0.50, s)))
    assert edge_check.simulate_taker_trades([{"model_prob": 0.52, "ask": 0.50, "outcome": 1}], s) == []


# ---- journal ----
def test_journal_gates_and_grouping(tmp_path):
    path = tmp_path / "paper.jsonl"
    ids = [journal.log_decision(path, strategy="C8", market=f"m{i}", group=f"g{i % 3}", ask=0.9, shares=10)
           for i in range(6)]
    for d in ids:
        journal.log_outcome(path, d, won=True)
    s = journal.summarize(path)
    assert s["decisions"] == 6 and s["independent_decisions"] == 3
    assert s["paper_gate_met"] is False and s["evidence_gate_met"] is False
    assert s["mean_net_pnl_per_decision"] == pytest.approx(2 * 10 * (1 - 0.9))  # two fills per group


def test_journal_is_append_only(tmp_path):
    path = tmp_path / "j.jsonl"
    d = journal.log_decision(path, strategy="x", market="m", group="g", ask=0.5, shares=1)
    journal.log_outcome(path, d, won=False)
    assert [json.loads(l)["kind"] for l in path.read_text().splitlines()] == ["decision", "outcome"]


# ---- safety ----
def test_live_needs_flag_env_and_no_kill_file(tmp_path, monkeypatch):
    kill = tmp_path / "KILL"
    with pytest.raises(safety.NotAllowed):
        safety.require_live(False, kill_file=kill, blocked=False)
    monkeypatch.delenv("POLYMARKET_STRATEGIES_LIVE", raising=False)
    with pytest.raises(safety.NotAllowed):
        safety.require_live(True, kill_file=kill, blocked=False)
    monkeypatch.setenv("POLYMARKET_STRATEGIES_LIVE", "1")
    safety.require_live(True, kill_file=kill, blocked=False)  # allowed
    kill.write_text("stop")
    with pytest.raises(safety.NotAllowed):
        safety.require_live(True, kill_file=kill, blocked=False)
    kill.unlink()
    with pytest.raises(safety.NotAllowed):
        safety.require_live(True, kill_file=kill, blocked=True)


def test_size_cap():
    assert safety.cap_size(500, 25) == 25 and math.isclose(safety.cap_size(10, 25), 10)


@pytest.mark.parametrize("requested,cap", [(float("nan"), 25), (10, float("inf")), (-1, 25), (10, -5), (True, 25), ("10", 25), (None, 25)])
def test_size_cap_refuses_values_that_are_not_finite_nonnegative_numbers(requested, cap):
    with pytest.raises(ValueError):
        safety.cap_size(requested, cap)


def test_state_folder_is_per_user_and_can_be_moved(tmp_path, monkeypatch):
    monkeypatch.delenv("POLYMARKET_STRATEGIES_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert safety.state_dir() == Path.home() / ".polymarket-strategies"
    monkeypatch.setenv("POLYMARKET_STRATEGIES_HOME", str(tmp_path / "elsewhere"))
    assert safety.state_dir() == tmp_path / "elsewhere" and safety.kill_files()[0] == tmp_path / "elsewhere" / "KILL"


@pytest.mark.parametrize("where", ["state", "cwd"])
def test_a_kill_file_in_the_state_folder_or_the_current_folder_stops_new_orders_from_any_directory(tmp_path, monkeypatch, where):
    state, here = tmp_path / "state", tmp_path / "here"
    state.mkdir(), here.mkdir()
    monkeypatch.setenv("POLYMARKET_STRATEGIES_HOME", str(state))
    monkeypatch.setenv("POLYMARKET_STRATEGIES_LIVE", "1")
    monkeypatch.chdir(here)
    safety.require_live(True, blocked=False)  # nothing stops it yet
    (state / "KILL" if where == "state" else here / "KILL").write_text("stop")
    with pytest.raises(safety.NotAllowed, match="kill switch engaged"):
        safety.require_live(True, blocked=False)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)  # a different folder: only the state-folder file still applies
    if where == "state":
        with pytest.raises(safety.NotAllowed, match="kill switch engaged"):
            safety.require_live(True, blocked=False)
    else:
        safety.require_live(True, blocked=False)


# ---- edge_check.best_blend ----
def test_best_blend_gives_zero_weight_to_a_copy_of_the_market_and_full_weight_to_a_sharper_model():
    outcomes = [1, 0, 1, 0, 1, 0]
    market = [0.5] * 6
    assert edge_check.best_blend(market, market, outcomes)["weight_on_model"] == 0.0  # nothing new: ties go to the market
    sharp = [0.9, 0.1, 0.9, 0.1, 0.9, 0.1]  # sorts the outcomes correctly, so trusting it fully is best
    b = edge_check.best_blend(sharp, market, outcomes)
    assert b["weight_on_model"] == 1.0 and b["blend_log_loss"] < b["market_log_loss"]


def test_best_blend_shrinks_an_overconfident_model_toward_the_market():
    outcomes = [1, 1, 0, 0, 0, 1, 1, 0, 1, 1]
    market = [0.7, 0.7, 0.7, 0.3, 0.3, 0.3, 0.5, 0.5, 0.8, 0.8]
    model = [0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.75, 0.75, 0.95, 0.95]
    b = edge_check.best_blend(model, market, outcomes)
    assert 0 < b["weight_on_model"] < 0.5 and b["blend_log_loss"] < b["market_log_loss"] < b["model_log_loss"]


# ---- fixes found by the independent check of Chapter 5 ----
@pytest.mark.parametrize("answer,allowed", [({"blocked": False}, True), ({"blocked": True}, False), ({}, False),
                                            ({"blocked": None}, False), ({"blocked": "no"}, False), ({"country": "XX"}, False)])
def test_geoblock_guard_fails_closed_on_anything_but_an_explicit_false(tmp_path, monkeypatch, answer, allowed):
    monkeypatch.setenv("POLYMARKET_STRATEGIES_LIVE", "1")
    monkeypatch.setattr(safety, "geoblock_status", lambda timeout=5.0: answer)
    if allowed:
        safety.require_live(True, kill_file=tmp_path / "KILL")
    else:
        with pytest.raises(safety.NotAllowed):
            safety.require_live(True, kill_file=tmp_path / "KILL")


def test_geoblock_guard_raises_when_the_check_itself_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYMARKET_STRATEGIES_LIVE", "1")

    def boom(timeout=5.0):
        raise OSError("network down")
    monkeypatch.setattr(safety, "geoblock_status", boom)
    with pytest.raises(OSError):
        safety.require_live(True, kill_file=tmp_path / "KILL")  # no order is placed


def test_a_second_outcome_line_cannot_rewrite_a_decision(tmp_path):
    path = tmp_path / "j.jsonl"
    d = journal.log_decision(path, strategy="x", market="m", group="g", ask=0.5, shares=10, role="maker")
    journal.log_outcome(path, d, won=False)
    journal.log_outcome(path, d, won=True)  # an attempt to flatter the record
    s = journal.summarize(path)
    assert s["win_rate"] == 0.0 and s["duplicate_outcomes"] == 1  # the first outcome stands, and the duplicate is reported
    assert json.loads(path.read_text().splitlines()[0])["role"] == "maker"


def test_a_degenerate_interval_is_not_evidence(tmp_path):
    path = tmp_path / "j.jsonl"
    for g in range(6):  # six losing groups: the interval is wholly below zero
        d = journal.log_decision(path, strategy="x", market=f"m{g}", group=f"g{g}", ask=0.9, shares=10)
        journal.log_outcome(path, d, won=False)
    s = journal.summarize(path)
    assert s["ci95"] is None and s["interval_excludes_zero"] is False and s["interval_above_zero"] is False


def test_all_winning_favorites_cannot_pass_the_evidence_screen(tmp_path):
    path = tmp_path / "j.jsonl"
    for g in range(300):
        d = journal.log_decision(path, strategy="favorite", market=f"m{g}", group=f"g{g}", ask=0.995, shares=1)
        journal.log_outcome(path, d, won=True)
    s = journal.summarize(path)
    assert s["sample_checkpoint_met"] is True and s["evidence_gate_met"] is False
    assert s["ci95"] is None and s["interval_above_zero"] is False
    assert 0.995 ** 300 == pytest.approx(0.2222922)  # this streak is quite possible at a fair price


def test_a_group_waits_for_all_its_linked_decisions(tmp_path):
    path = tmp_path / "j.jsonl"
    a = journal.log_decision(path, strategy="basket", market="a", group="event", ask=0.4, shares=1)
    journal.log_decision(path, strategy="basket", market="b", group="event", ask=0.6, shares=1)
    journal.log_outcome(path, a, won=True)
    s = journal.summarize(path)
    assert (s["resolved"], s["analyzed_decisions"], s["independent_decisions"], s["pending_groups"]) == (1, 0, 0, 1)


def test_pending_groups_keep_the_evidence_screen_off(tmp_path):
    # 400 groups fixed in advance at 80 cents: 285 of the 300 that resolved won, and 100 are pending.
    # The resolved groups look good (+$0.15 a group); if the pending ones lose, the whole sample averages -$0.0875.
    path = tmp_path / "j.jsonl"
    for g in range(400):
        d = journal.log_decision(path, strategy="x", market=f"m{g}", group=f"g{g}", ask=0.8, shares=1)
        if g < 300:
            journal.log_outcome(path, d, won=g >= 15)
    s = journal.summarize(path)
    assert s["independent_decisions"] == 300 and s["pending_groups"] == 100
    assert s["mean_net_pnl_per_decision"] == pytest.approx(0.15) and s["interval_above_zero"] is True
    assert s["evidence_gate_met"] is False and "100 logged groups have not resolved" in s["pending_warning"]
    assert (285 * 0.2 - 115 * 0.8) / 400 == pytest.approx(-0.0875)


def test_wilson_interval():
    lo, hi = edge_check.wilson_interval(6, 10)
    assert (round(lo, 3), round(hi, 3)) == (0.313, 0.832)
    lo, hi = edge_check.wilson_interval(120, 200)
    assert (round(lo, 3), round(hi, 3)) == (0.531, 0.665)  # the chapter's example: 200 events, and the low end clears a 53% break-even


def test_wilson_interval_stays_inside_zero_to_one_for_unanimous_histories_of_every_length():
    """Round-off used to give -1.4e-17 for 0 of 20 and 1.0000000000000002 for 19 of 19, which Strategy 19 then rejected."""
    for n in range(1, 301):
        assert 0.0 <= edge_check.wilson_interval(0, n)[0] < 1e-12 and 0 < edge_check.wilson_interval(0, n)[1] < 1  # the exact low end is 0
        assert 1 - 1e-12 < edge_check.wilson_interval(n, n)[1] <= 1.0 and 0 < edge_check.wilson_interval(n, n)[0] < 1
        for k in (0, n // 2, n):
            lo, hi = edge_check.wilson_interval(k, n)
            assert 0.0 <= lo <= k / n <= hi <= 1.0


@pytest.mark.parametrize("successes,n", [(1, 0), (-1, 5), (6, 5), (float("nan"), 5), (True, 5), (1, 5.0), (1, True), (1, -3)])
def test_wilson_interval_refuses_impossible_counts(successes, n):
    with pytest.raises(ValueError):
        edge_check.wilson_interval(successes, n)


def test_calc_takes_the_markets_own_rate(capsys):
    """`calc --rate` replaces the category's rate: 0.07 x 0.52 x 0.48 is 1.7472 cents a share, 1.7472 dollars on 100 shares."""
    import json

    from polymarket_strategies.__main__ import main

    main(["calc", "--price", "0.52", "--rate", "0.07", "--prob", "0.60"])
    out = json.loads(capsys.readouterr().out)
    assert out["taker_fee_usdc"] == 1.7472
    assert round(out["break_even_probability"], 4) == 0.5375
    main(["calc", "--category", "crypto", "--price", "0.52"])
    assert json.loads(capsys.readouterr().out)["taker_fee_usdc"] == 1.7472


def _fake_public_client(monkeypatch, markets):
    """Stand in for the SDK's public client: `list_markets` returns the markets whose `closed` flag matches the request."""
    from types import SimpleNamespace as NS

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def list_markets(self, **kwargs):
            async def first_page():
                return NS(items=[m for m in markets if m.closed == kwargs["closed"]])
            return NS(first_page=first_page)
    monkeypatch.setattr("polymarket.AsyncPublicClient", Client)


def _market(slug="stand-in", closed=False, fees_enabled=True, rate=0.05):
    from types import SimpleNamespace as NS
    schedule = NS(rate=rate, exponent=1, rebate_rate=0.25, taker_only=True)
    return NS(slug=slug, closed=closed, trading=NS(fees_enabled=fees_enabled, fee_schedule=schedule))


def _calc(capsys, *args):
    import json

    from polymarket_strategies.__main__ import main
    main(["calc", *args])
    return json.loads(capsys.readouterr().out)


def test_calc_names_the_fee_schedule_it_used_and_defaults_are_visible(capsys):
    assert _calc(capsys, "--price", "0.5", "--category", "crypto")["fee_schedule"] == {
        "source": "the crypto category", "taker_rate": 0.07, "exponent": 1.0, "maker_rebate_share": 0.2}
    assert "politics category (the default" in _calc(capsys, "--price", "0.5")["fee_schedule"]["source"]
    assert _calc(capsys, "--price", "0.5", "--rate", "0.05")["fee_schedule"]["source"] == "--rate"


def test_calc_output_has_no_float_noise(capsys):
    assert _calc(capsys, "--price", "0.5", "--rate", "0.04", "--shares", "7")["fee_fraction_of_cost"] == 0.02


@pytest.mark.parametrize("args", [["--category", "bogus"], ["--days", "0.5"], ["--days", "0.001"]])
def test_calc_refuses_a_category_it_does_not_know_and_periods_too_short_to_annualize(args, capsys):
    from polymarket_strategies.__main__ import main
    with pytest.raises(SystemExit) as failure:
        main(["calc", "--price", "0.95", *args])
    assert failure.value.code == 2 and "Traceback" not in capsys.readouterr().err


def test_calc_reads_the_markets_own_schedule_from_the_exact_slug(monkeypatch, capsys):
    _fake_public_client(monkeypatch, [_market("other-market", rate=0.01), _market("wanted", rate=0.07)])
    out = _calc(capsys, "--price", "0.5", "--slug", "wanted")
    assert out["fee_schedule"]["taker_rate"] == 0.07 and "wanted" in out["fee_schedule"]["source"]


def test_calc_does_not_use_a_market_with_a_different_slug_and_falls_back_to_closed_markets(monkeypatch, capsys):
    from polymarket_strategies.__main__ import main
    _fake_public_client(monkeypatch, [_market("other-market", rate=0.01), _market("old", closed=True, rate=0.03)])
    assert _calc(capsys, "--price", "0.5", "--slug", "old")["fee_schedule"]["taker_rate"] == 0.03
    with pytest.raises(SystemExit) as failure:
        main(["calc", "--price", "0.5", "--slug", "missing"])
    assert failure.value.code == 2 and "no market with the slug" in capsys.readouterr().err


def test_calc_reports_unknown_fee_metadata_instead_of_a_traceback(monkeypatch, capsys):
    from polymarket_strategies.__main__ import main
    _fake_public_client(monkeypatch, [_market("wanted", fees_enabled=None)])
    with pytest.raises(SystemExit) as failure:
        main(["calc", "--price", "0.5", "--slug", "wanted"])
    err = capsys.readouterr().err
    assert failure.value.code == 2 and "unavailable or inconsistent" in err and "Traceback" not in err


@pytest.mark.parametrize("call", [
    lambda: sizing.kelly_fraction(1.5, 0.5), lambda: sizing.kelly_fraction(0.6, 1.2), lambda: sizing.kelly_fraction(0.6, 0.5, -0.1),
    lambda: sizing.kelly_fraction(float("nan"), 0.5), lambda: sizing.fractional_kelly(-0.1), lambda: sizing.fractional_kelly(2),
    lambda: sizing.cap_clusters({"a": -0.1}, {"a": "x"}, 0.05), lambda: sizing.cap_clusters({"a": 0.1}, {}, 0.05),
    lambda: sizing.cap_clusters({"a": 0.1}, {"a": "x"}, -1), lambda: sizing.martingale_exposure(10, -1), lambda: sizing.martingale_exposure(10, 10**9),
    lambda: sizing.martingale_exposure(-10, 3), lambda: sizing.expected_trades_to_losing_streak(0), lambda: sizing.expected_trades_to_losing_streak(7, 1),
    lambda: sizing.expected_trades_to_losing_streak(7, 0), lambda: sizing.expected_trades_to_losing_streak(1000, 0.001),
    lambda: carry.return_if_win(0.95, 0.06), lambda: carry.return_if_win(1.2), lambda: carry.return_if_win(0.5, -0.1),
    lambda: carry.wins_needed_per_loss(0.99, 0.02), lambda: carry.wins_needed_per_loss(0),
    lambda: carry.annualized(-1.5, 30), lambda: carry.annualized(-1, 30), lambda: carry.annualized(0.05, 0), lambda: carry.annualized(0.0505, 0.01),
    lambda: carry.holding_reward_hourly(-1, 0.5, 0, 0), lambda: carry.holding_reward_hourly(10, 1.5, 0, 0), lambda: carry.holding_reward_hourly(10, 0.5, 0, 0, 3.25),
])
def test_sizing_and_carry_refuse_impossible_inputs_instead_of_returning_nonsense(call):
    with pytest.raises(ValueError):
        call()


def test_journal_skips_blank_lines_reports_orphan_outcomes_and_can_filter_by_strategy(tmp_path, capsys):
    from polymarket_strategies.__main__ import main
    path = tmp_path / "j.jsonl"
    a = journal.log_decision(path, strategy="carry", market="m1", group="g1", ask=0.9, shares=10)
    b = journal.log_decision(path, strategy="weather", market="m2", group="g2", ask=0.4, shares=10)
    journal.log_outcome(path, a, won=True)
    journal.log_outcome(path, b, won=False)
    journal.log_outcome(path, "typo-id", won=True)  # matches no decision
    path.write_text(path.read_text() + "\n\n")  # blank lines at the end used to crash the summary
    s = journal.summarize(path)
    assert s["orphan_outcomes"] == 1 and s["strategies"] == ["carry", "weather"] and "mixes strategies" in s["strategy_warning"]
    assert s["resolved"] == 2
    only = journal.summarize(path, strategy="carry")
    assert only["resolved"] == 1 and only["win_rate"] == 1.0 and "strategy_warning" not in only and only["orphan_outcomes"] == 1
    main(["journal-summary", str(path), "--strategy", "weather"])
    assert json.loads(capsys.readouterr().out)["win_rate"] == 0.0


def test_the_live_switch_must_be_exactly_one_and_any_kill_entry_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYMARKET_STRATEGIES_HOME", str(tmp_path))
    for value in ("0", "true", "yes", ""):
        monkeypatch.setenv("POLYMARKET_STRATEGIES_LIVE", value)
        with pytest.raises(safety.NotAllowed, match="POLYMARKET_STRATEGIES_LIVE=1"):
            safety.require_live(True, blocked=False)
    monkeypatch.setenv("POLYMARKET_STRATEGIES_LIVE", "1")
    safety.require_live(True, blocked=False)
    (tmp_path / "KILL").symlink_to(tmp_path / "nowhere")  # a broken link is still an entry named KILL
    with pytest.raises(safety.NotAllowed, match="kill switch engaged"):
        safety.require_live(True, blocked=False)


def test_a_relative_state_folder_is_refused_everywhere_and_a_tilde_one_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("POLYMARKET_STRATEGIES_HOME", "state")
    monkeypatch.setenv("POLYMARKET_STRATEGIES_LIVE", "1")  # so require_live reaches the kill-switch check
    for folder in ("here", "elsewhere"):
        (tmp_path / folder).mkdir(exist_ok=True)
        monkeypatch.chdir(tmp_path / folder)
        for call in (safety.state_dir, safety.kill_files, lambda: safety.require_live(True, blocked=False)):
            with pytest.raises(ValueError, match="absolute"):
                call()  # never a different ledger or KILL file for each folder (RK-01)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("POLYMARKET_STRATEGIES_HOME", "~/own-folder")
    assert safety.state_dir() == tmp_path / "own-folder" and safety.kill_files()[0] == tmp_path / "own-folder" / "KILL"


def test_calculators_refuse_garbage_at_the_boundary():
    import math
    with pytest.raises(ValueError):
        edge_check.bootstrap_mean([])
    with pytest.raises(ValueError):
        edge_check.bootstrap_mean([float("nan"), 1.0])
    with pytest.raises(ValueError):
        edge_check.wilson_interval(5, 10**400)
    with pytest.raises(ValueError):
        edge_check.simulate_taker_trades([{"model_prob": 0.6, "ask": 0.5, "outcome": 2}], fees.FeeSchedule(0.04))
    with pytest.raises(ValueError):
        edge_check.simulate_taker_trades([{"model_prob": float("nan"), "ask": 0.5, "outcome": 1}], fees.FeeSchedule(0.04))
    with pytest.raises(ValueError):
        sizing.martingale_exposure(1e10, 1000)
    with pytest.raises(ValueError):
        carry.annualized(0.05, 1e-308)
    assert math.isfinite(sum(edge_check.bootstrap_mean([1.0, 2.0, 3.0])))


def test_calc_and_the_file_tools_end_in_plain_errors_not_tracebacks(tmp_path, capsys):
    from polymarket_strategies import __main__ as cli, constraint_scan
    with pytest.raises(SystemExit) as stopped:
        cli.main(["calc", "--price", "0.001", "--days", "1"])
    assert stopped.value.code == 2 and "too short to annualize" in capsys.readouterr().err
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n")
    for argv in (["journal-summary", str(bad)], ["journal-summary", str(tmp_path / "missing.jsonl")]):
        with pytest.raises(SystemExit) as stopped:
            cli.main(argv)
        assert stopped.value.code == 2 and "cannot summarize" in capsys.readouterr().err
    pairs = tmp_path / "pairs.json"
    for text in ('{"a": 1}', '[{"smaller": 1, "larger": "b"}]', "not json"):
        pairs.write_text(text)
        with pytest.raises(SystemExit) as stopped:
            constraint_scan.main([str(pairs)])
        assert stopped.value.code == 2 and "cannot use" in capsys.readouterr().err
    with pytest.raises(SystemExit) as stopped:
        constraint_scan.main([str(tmp_path / "nope.json")])
    assert stopped.value.code == 2 and "cannot use" in capsys.readouterr().err


# ---- formulas and checks that a mutation run (RK, second revision) found no test could fail
def test_fee_formula_uses_the_schedules_exponent_and_the_range_checks_hold():
    from types import SimpleNamespace as NS
    assert fees.fee_per_share(0.3, fees.FeeSchedule(rate=0.04, exponent=2)) == pytest.approx(0.04 * (0.3 * 0.7) ** 2)
    assert fees.fee_per_share(0.3, fees.FeeSchedule(rate=0.04, exponent=1)) == pytest.approx(0.04 * 0.3 * 0.7)

    def market(**schedule):
        base = dict(rate=0.04, exponent=1, rebate_rate=0.2, taker_only=True)
        return NS(trading=NS(fees_enabled=True, fee_schedule=NS(**(base | schedule))))
    assert fees.schedule_from_market(market()) == fees.FeeSchedule(0.04, 1, 0.2, True)
    for bad in (dict(rebate_rate=1.5), dict(rebate_rate=-0.1), dict(taker_only="yes"), dict(taker_only=None), dict(rate=-1), dict(exponent=-1)):
        with pytest.raises(ValueError, match="invalid"):
            fees.schedule_from_market(market(**bad))


def test_the_bootstrap_percentiles_are_pinned_and_the_wilson_interval_refuses_impossible_counts():
    values = [0.13, 0.57, 0.91, 0.22, 0.68, 0.35, 0.79, 0.44, 0.05, 0.86]
    mean, low, high = edge_check.bootstrap_mean(values, n_boot=2000, seed=0)
    assert (mean, low, high) == pytest.approx((0.5, 0.32, 0.684), abs=1e-9)  # the 2.5th and 97.5th of 2,000 resampled means
    for successes in (10.4, 11, -1, float("nan")):
        with pytest.raises(ValueError):
            edge_check.wilson_interval(successes, 10)


def test_a_fade_is_worth_its_two_outcomes_and_a_basket_walk_refuses_an_infinite_profit():
    from polymarket_strategies import baskets, reaction
    # the YES price jumps from 0.40 to 0.60; with a 30% chance the rumor is true: 0.7 x (+0.20) - 0.3 x (0.40)
    assert reaction.fade_value(0.40, 0.60, 0.30) == pytest.approx(0.02)
    assert reaction.fade_value(0.40, 0.60, 0.0) == pytest.approx(0.20) and reaction.fade_value(0.40, 0.60, 1.0) == pytest.approx(-0.40)
    with pytest.raises(ValueError, match="finite"):
        baskets.walk([[(0.5, 10.0)], [(0.4, 10.0)]], lambda prices: float("inf"))


class _Reply:
    """What urlopen returns: a context manager with a readable JSON body."""
    def __init__(self, body):
        self.body = body
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *args):
        return self.body


def test_the_geoblock_request_names_the_tool_because_polymarket_refuses_pythons_default_agent(monkeypatch):
    seen = []
    monkeypatch.setattr(safety.urllib.request, "urlopen", lambda request, timeout=None: seen.append(request) or _Reply(b'{"blocked": false}'))
    assert safety.geoblock_status() == {"blocked": False}
    assert seen[0].full_url == safety.GEOBLOCK_URL and seen[0].get_header("User-agent") == safety.USER_AGENT != "Python-urllib"
    assert safety.USER_AGENT.startswith("polymarket-strategies")  # both endpoints answered HTTP 403 to Python's default agent on 3 Oct 2026


def test_calc_does_not_invent_a_maker_rebate_when_only_the_taker_rate_is_given(capsys):
    from polymarket_strategies import __main__ as cli
    cli.main(["calc", "--rate", "0.05", "--price", "0.5"])
    assert json.loads(capsys.readouterr().out)["fee_schedule"]["maker_rebate_share"] is None
    cli.main(["calc", "--category", "crypto", "--price", "0.5"])
    assert json.loads(capsys.readouterr().out)["fee_schedule"]["maker_rebate_share"] == fees.CATEGORY_FEES["crypto"][1]


def test_calc_refuses_an_infinite_or_undefined_number_of_days(capsys):
    from polymarket_strategies import __main__ as cli
    for days in ("inf", "nan", "0.5"):
        with pytest.raises(SystemExit) as stopped:
            cli.main(["calc", "--price", "0.5", "--days", days])
        assert stopped.value.code == 2 and "days" in capsys.readouterr().err
