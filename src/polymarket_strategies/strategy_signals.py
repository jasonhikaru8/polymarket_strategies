"""Indexed news, execution, quoting and monitoring analyses; no network or orders.

``analyze(index, inputs, now=...)`` consumes reader-supplied observations. Every
schema has this envelope: target_yes_definition, resolution_source, evidence,
source_notes, as_of, valid_until, contract {yes_definition, resolution_source,
end_time}, outcome, limit_price, fee_per_share, min_edge. Times are UTC epoch
seconds; prices are dollars per share. ``fee_per_share`` and
``bid_fill_fee_per_share`` are the cash fee per share a BUY pays on top of its
price; a BUY receives every matched share. Exit and ask fee fields are the cash
fee per share taken out of SELL proceeds. Quantity, depth, inventory, order and
wallet-history sizes are plain share counts. ``demo_inputs`` supplies complete
synthetic schemas.

15/16/17/18/25/34 may return a held-to-resolution model_value forecast. Those
probabilities and uncertainty bounds must be supplied by the reader; a headline,
attention count or rumor confidence is never automatically a contract forecast.
22/23/24/26/27/28/29/30/31 are analysis/proposal/monitor tools. Their eligibility
means their stated analytical screen passed, never permission to send an order.
Public-source attestations and calibration/comparability checks are recorded
reader assertions, not independent verification of a source or legal advice.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .reaction import implied_chance_true
from .reward_score import min_score, side_score
from .strategies import _number, _text, evaluate
from .wallet_audit import audit


SUPPORTED = (15, 16, 17, 18, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 34)


def _num(inputs, field, *, low=None, high=None):
    return _number(inputs[field], field, low=low, high=high)


def _positive(inputs, field):
    value = _num(inputs, field, low=0)
    if value == 0:
        raise ValueError(f"{field} must be positive")
    return value


def _true(inputs, field):
    if inputs[field] is not True:
        raise ValueError(f"{field} must be explicitly true")


def _object(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _past(inputs, field, now):
    value = _num(inputs, field, low=0)
    if value > now:
        raise ValueError(f"{field} cannot be in the future")
    return value


def _fresh_quote(inputs, now):
    quote = _past(inputs, "quote_at", inputs["as_of"])
    if now - quote > _positive(inputs, "max_quote_age_seconds"):
        raise ValueError("quote is stale")
    return quote


def _envelope(inputs, now, index):
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be an object")
    _number(now, "now", low=0)
    for field in ("target_yes_definition", "resolution_source", "evidence", "source_notes"):
        _text(inputs[field], field)
    if not _num(inputs, "as_of", low=0) <= now < _num(inputs, "valid_until", low=0):
        raise ValueError("observations must already exist and remain valid at the decision")
    contract = inputs["contract"]
    if not isinstance(contract, dict):
        raise ValueError("contract must be an object")
    if inputs["target_yes_definition"] != contract["yes_definition"]:
        raise ValueError("target YES definition does not match the reviewed contract")
    if inputs["resolution_source"] != contract["resolution_source"]:
        raise ValueError("resolution source does not match the reviewed contract")
    end = _num(contract, "end_time", low=0)
    if index != 26 and end <= now:
        raise ValueError("contract must end after the decision")
    if inputs["outcome"] not in ("YES", "NO"):
        raise ValueError("outcome must be YES or NO")
    price = _num(inputs, "limit_price", low=0, high=1)
    fee = _num(inputs, "fee_per_share", low=0)
    if not 0 < price < 1 or price + fee >= 1:
        raise ValueError("entry cost must be strictly between zero and one dollar")
    _num(inputs, "min_edge", low=0)


def _forecast(inputs, now, result):
    fields = ("probability_yes", "conservative_low_yes", "conservative_high_yes",
              "as_of", "valid_until", "target_yes_definition", "resolution_source", "evidence", "source_notes")
    forecast = {field: inputs[field] for field in fields}
    decision = evaluate({"kind": "model_value", "inputs": forecast, "min_edge": inputs["min_edge"]},
                        outcome=inputs["outcome"], limit_price=inputs["limit_price"],
                        fee_per_share=inputs["fee_per_share"], now=now,
                        end_time=inputs["contract"]["end_time"], resolution_source=inputs["resolution_source"],
                        yes_definition=inputs["target_yes_definition"])
    result["analysis"]["decision"] = decision
    result["reasons"].extend(decision["reasons"])
    if decision["eligible"]:
        result["forecast"] = forecast


def _public_report(report, now):
    if not isinstance(report, dict):
        raise ValueError("report must be an object")
    for field in ("url", "summary", "archive_sha256"):
        _text(report[field], f"report.{field}")
    if not report["url"].startswith(("https://", "http://")):
        raise ValueError("report URL must be a public HTTP(S) source")
    digest = report["archive_sha256"]
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("archive_sha256 must contain 64 lowercase hexadecimal characters")
    _true(report, "publicly_accessible")
    _true(report, "provenance_reviewed")
    published = _past(report, "published_at", now)
    received = _past(report, "received_at", now)
    if published > received:
        raise ValueError("report receipt cannot precede publication")
    return published, received


def _records(records, now, *, time_field="timestamp"):
    if not isinstance(records, list) or not records:
        raise ValueError("history must be a nonempty list")
    ids = set()
    previous = -1.0
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("each history record must be an object")
        ident = _text(row["id"], "history.id")
        stamp = _past(row, time_field, now)
        if ident in ids:
            raise ValueError("history IDs must be unique")
        if stamp < previous:
            raise ValueError("history must be ordered by observation time")
        ids.add(ident)
        previous = stamp
    return records


def _trade_rows(rows, now):
    for row in _records(rows, now):
        _text(row["event"], "event")
        size = _positive(row, "size")
        cash = _positive(row, "cash_notional_usdc")
        price = _num(row, "price", low=0, high=1)
        if not 0 < price < 1:
            raise ValueError("trade prices must be strictly between zero and one")
        if row["side"] not in ("BUY", "SELL"):
            raise ValueError("trade side must be BUY or SELL")
        # A BUY's cash may include its fee and a SELL's may be net of it; a wider gap means cents or base units.
        if abs(cash - size * price) > 0.02 * size + 0.01:
            raise ValueError("cash_notional_usdc must be the trade's dollars: size x price, within 2 cents "
                             "a share for fees plus 1 cent of rounding")
    return rows


def _news(index, inputs, now, result):
    published, received = _public_report(inputs["report"], now)
    if inputs["as_of"] < received:
        raise ValueError("forecast cannot predate receipt of its report")
    _true(inputs, "report_matches_contract_reviewed")
    if index == 34:
        if inputs["duty_restricted"] is not False or inputs["can_influence_outcome"] is not False:
            raise ValueError("public information workflow requires no duty restriction or outcome influence")
    result["analysis"].update(publication_to_receipt_seconds=received - published,
                               seconds_since_receipt=now - received,
                               source_verification="Reader-attested provenance; not independently verified.")
    _forecast(inputs, now, result)


def _fade(inputs, now, result):
    pre = _num(inputs, "pre_news_yes", low=0, high=1)
    spike = _num(inputs, "spike_yes", low=0, high=1)
    if not 0 <= pre < spike < 1:
        raise ValueError("fade requires a YES spike above baseline and below one")
    if inputs["outcome"] != "NO":
        raise ValueError("this upward-spike fade buys NO")
    result["analysis"]["implied_rumor_confidence_under_two_state_assumption"] = implied_chance_true(pre, spike)
    if inputs["mode"] == "held_to_resolution":
        _true(inputs, "resolution_forecast_reviewed")
        _forecast(inputs, now, result)
    elif inputs["mode"] == "exit_mark":
        chance = _num(inputs, "rumor_confirmation_probability", low=0, high=1)
        yes_confirmed = _num(inputs, "exit_yes_if_confirmed", low=0, high=1)
        yes_denied = _num(inputs, "exit_yes_if_denied", low=0, high=1)
        confirmed_fee = _num(inputs, "exit_fee_if_confirmed", low=0)
        denied_fee = _num(inputs, "exit_fee_if_denied", low=0)
        slippage = _num(inputs, "slippage_reserve", low=0)
        expected_exit = chance * (1 - yes_confirmed) + (1 - chance) * (1 - yes_denied)
        expected_fee = chance * confirmed_fee + (1 - chance) * denied_fee
        edge = expected_exit - inputs["limit_price"] - inputs["fee_per_share"] - expected_fee - slippage
        result["analysis"].update(expected_exit_mark=expected_exit, expected_profit_per_share=edge,
                                   limitation="Exit scenarios require future fills; rumor confidence is not a contract probability.")
        if edge < inputs["min_edge"]:
            result["reasons"].append("expected exit profit after two fees and slippage is below min_edge")
    else:
        raise ValueError("fade mode must be held_to_resolution or exit_mark")


def _macro(inputs, now, result):
    release = _past(inputs, "release_at", now)
    benchmark = _past(inputs, "benchmark_fixed_at", now)
    received = _past(inputs, "actual_received_at", now)
    if not benchmark < release <= received <= inputs["as_of"]:
        raise ValueError("benchmark must precede release, then receipt, then forecast")
    _true(inputs, "contract_response_model_reviewed")
    actual = _num(inputs, "actual")
    consensus = _num(inputs, "consensus")
    scale = _positive(inputs, "surprise_scale")
    _text(inputs["release_units"], "release_units")
    result["analysis"].update(surprise=actual - consensus, standardized_surprise=(actual - consensus) / scale,
                               limitation="The surprise is descriptive; the reader supplies the calibrated contract forecast.")
    _forecast(inputs, now, result)


def _attention(inputs, now, result):
    _true(inputs, "attention_model_reviewed")
    counts = []
    periods = []
    for name in ("baseline", "current"):
        period = _object(inputs[f"{name}_period"], f"{name}_period")
        count = _num(period, "count", low=0)
        if not count.is_integer():
            raise ValueError("attention counts must be integers")
        start = _past(period, "start", now)
        end = _past(period, "end", inputs["as_of"])
        if end <= start:
            raise ValueError("attention periods must have positive duration")
        counts.append(count / (end - start))
        periods.append((start, end))
    if periods[0][1] > periods[1][0]:
        raise ValueError("baseline and current attention periods must not overlap")
    minimum = _positive(inputs, "min_rate_ratio")
    ratio = counts[1] / counts[0] if counts[0] else None
    result["analysis"].update(baseline_rate=counts[0], current_rate=counts[1], rate_ratio=ratio,
                               limitation="More attention does not determine a contract's outcome probability.")
    if ratio is None:
        result["reasons"].append("zero baseline cannot establish a finite rate ratio")
    elif ratio < minimum:
        result["reasons"].append("attention growth is below min_rate_ratio")
    _forecast(inputs, now, result)


def _latency(index, inputs, now, result):
    _true(inputs, "reference_matches_contract")
    _true(inputs, "observation_confirmed")
    event = _past(inputs, "event_at", now)
    receipt = _past(inputs, "feed_received_at", now)
    _fresh_quote(inputs, now)
    if not event <= receipt <= inputs["as_of"]:
        raise ValueError("event, receipt and quote cannot postdate the recorded observation")
    execution = _positive(inputs, "execution_latency_seconds")
    clock = _num(inputs, "clock_uncertainty_seconds", low=0)
    delay = _num(inputs, "sports_order_delay_seconds", low=0) if index == 23 else 0
    deadline = _num(inputs, "opportunity_expires_at", low=0)
    conservative = _num(inputs, "conservative_outcome_probability", low=0, high=1)
    edge = conservative - inputs["limit_price"] - inputs["fee_per_share"]
    remaining = deadline - now
    earliest = execution + delay + clock
    if deadline > inputs["contract"]["end_time"]:
        raise ValueError("opportunity window cannot extend beyond the contract deadline")
    result["analysis"].update(feed_delay_seconds=receipt - event, remaining_window_seconds=remaining,
                               earliest_match_delay_seconds=earliest, conservative_edge_per_share=edge,
                               limitation="Supplied timing scenario only; no live feed, fast executor or automatic exit.")
    if earliest >= remaining:
        result["reasons"].append("execution delay and clock uncertainty exhaust the opportunity window")
    if edge < inputs["min_edge"]:
        result["reasons"].append("conservative edge is below min_edge")


def _scalp(inputs, now, result):
    entry = _num(inputs, "entry_ask", low=0, high=1)
    exit_bid = _num(inputs, "planned_exit_bid", low=0, high=1)
    if not 0 < entry < 1 or not 0 < exit_bid < 1:
        raise ValueError("scalping marks must be strictly between zero and one")
    if entry > inputs["limit_price"]:
        raise ValueError("entry ask exceeds the supplied limit")
    exit_fee = _num(inputs, "exit_fee_per_share", low=0)
    slip = _num(inputs, "slippage_reserve", low=0)
    size = _positive(inputs, "quantity")
    for field in ("entry_depth", "exit_depth_estimate"):
        if _num(inputs, field, low=0) < size:
            result["reasons"].append(f"{field} does not cover the planned size")
    _fresh_quote(inputs, now)
    holding = _num(inputs, "exit_deadline", low=0) - now
    if not 0 < holding <= _positive(inputs, "max_holding_seconds"):
        raise ValueError("exit deadline is outside the maximum holding window")
    if inputs["exit_deadline"] > inputs["contract"]["end_time"]:
        raise ValueError("planned exit cannot follow the contract deadline")
    edge = exit_bid - entry - inputs["fee_per_share"] - exit_fee - slip
    result["analysis"].update(planned_profit_per_share=edge, planned_profit_usdc=edge * size,
                               limitation="Projected exit bid and depth need future fills. No automatic stop or exit order.")
    if edge < inputs["min_edge"]:
        result["reasons"].append("planned round-trip edge after fees and slippage is below min_edge")


def _rules(inputs, now, result):
    if inputs["contract_status"] != "open":
        raise ValueError("rules workflow is restricted to open, non-resolution markets")
    review = _object(inputs["rule_review"], "rule_review")
    for field in ("source_match", "timezone", "units", "cutoff", "ties", "exceptions"):
        _true(review, field)
    published, received = _public_report(inputs["source_document"], now)
    if inputs["source_document"]["source_id"] != inputs["resolution_source"]:
        raise ValueError("reviewed document does not identify the contract's resolution source")
    if received > inputs["as_of"]:
        raise ValueError("source document cannot postdate the forecast")
    result["analysis"].update(rule_checks=list(review), source_document_age_seconds=now - published,
                               limitation="Reader-reviewed source interpretation; fresh contract fingerprint is checked before trading.")
    _forecast(inputs, now, result)


def _dispute(inputs, now, result):
    phase = inputs["phase"]
    if phase not in ("open", "proposed", "disputed", "voting", "resolved"):
        raise ValueError("unknown resolution phase")
    proposal = inputs["proposal_at"]
    deadline = inputs["challenge_deadline"]
    if phase != "open":
        proposal = _past(inputs, "proposal_at", inputs["as_of"])
        deadline = _num(inputs, "challenge_deadline", low=0)
        if deadline <= proposal:
            raise ValueError("challenge deadline must follow the proposal")
    elif proposal is not None or deadline is not None:
        raise ValueError("open phase must not claim a resolution proposal")
    estimate = _num(inputs, "settlement_eta", low=0)
    _text(inputs["status_source"], "status_source")
    result["analysis"].update(phase=phase, challenge_open=phase == "proposed" and now < deadline,
                               hours_to_estimated_settlement=max(0, estimate - now) / 3600,
                               capital_at_risk_per_share=inputs["limit_price"],
                               maximum_payout_margin_before_fees=1 - inputs["limit_price"],
                               monitor_alert=phase in ("proposed", "disputed", "voting"),
                               limitation="Resolution monitor only; a proposal, tally or elapsed challenge does not guarantee payout.")


def _quotes(inputs, now, result, fair):
    half = _positive(inputs, "half_spread")
    inventory = _num(inputs, "inventory", low=0)
    target = _num(inputs, "target_inventory", low=0)
    maximum = _positive(inputs, "max_inventory")
    sensitivity = _num(inputs, "inventory_price_per_share", low=0)
    bid_size = _positive(inputs, "bid_size")
    ask_size = _positive(inputs, "ask_size")
    tick = _positive(inputs, "tick_size")
    if tick >= 1:
        raise ValueError("tick_size must be less than one")
    if inventory > maximum or target > maximum:
        raise ValueError("inventory and target must fit max_inventory")
    grid = Decimal(str(tick))
    center_decimal = Decimal(str(fair)) - Decimal(str(sensitivity)) * (Decimal(str(inventory)) - Decimal(str(target)))
    center = float(center_decimal)
    bid = float(((center_decimal - Decimal(str(half))) / grid).to_integral_value(rounding=ROUND_FLOOR) * grid)
    ask = float(((center_decimal + Decimal(str(half))) / grid).to_integral_value(rounding=ROUND_CEILING) * grid)
    if not 0 < bid < ask < 1:
        raise ValueError("inventory-derived quotes are outside the binary price range")
    best_bid = _num(inputs, "best_bid", low=0, high=1)
    best_ask = _num(inputs, "best_ask", low=0, high=1)
    if not best_bid < best_ask:
        raise ValueError("reference book is crossed or locked")
    _fresh_quote(inputs, now)
    buy_fee = _num(inputs, "bid_fill_fee_per_share", low=0)
    sell_fee = _num(inputs, "ask_fill_fee_per_share", low=0)
    adverse = _num(inputs, "adverse_selection_per_fill", low=0)
    buy_edge = fair - bid - buy_fee - adverse
    sell_edge = ask - fair - sell_fee - adverse
    round_trip = ask - bid - buy_fee - sell_fee - 2 * adverse
    result["analysis"].update(fair_outcome_probability=fair, inventory_shift=center - fair,
                               bid_proposal={"price": bid, "size": bid_size}, ask_proposal={"price": ask, "size": ask_size},
                               bid_edge_after_fee_and_adverse_selection=buy_edge,
                               ask_edge_after_fee_and_adverse_selection=sell_edge,
                               round_trip_margin=round_trip,
                               limitation="Quote proposals only; inventory, independent fills and adverse selection need a live two-sided manager.")
    if bid >= best_ask or ask <= best_bid:
        result["reasons"].append("a proposed passive quote crosses the observed opposite side")
    if inventory + bid_size > maximum or ask_size > inventory:
        result["reasons"].append("proposal exceeds inventory capacity or available shares")
    if min(buy_edge, sell_edge) < inputs["min_edge"]:
        result["reasons"].append("one quoting side fails min_edge after fee and adverse selection")


def _rewards(inputs, now, result):
    _true(inputs, "program_active")
    _true(inputs, "rewards_eligible")
    minimum_size = _positive(inputs, "minimum_size")
    spread = _positive(inputs, "max_spread_cents")
    midpoint = _num(inputs, "size_adjusted_midpoint", low=0, high=1)
    orders = inputs["orders"]
    if not isinstance(orders, list) or not orders or not all(isinstance(order, dict) for order in orders):
        raise ValueError("reward orders must be a nonempty list of objects")
    groups = {"one": [], "two": []}
    ids = set()
    for order in orders:
        ident = _text(order["id"], "order.id")
        if ident in ids:
            raise ValueError("reward order IDs must be unique")
        ids.add(ident)
        if order["score_side"] not in ("one", "two"):
            raise ValueError("score_side must be one or two from the documented complementary groups")
        distance = _num(order, "spread_cents", low=0)
        size = _positive(order, "size")
        if size < minimum_size or distance >= spread:
            result["reasons"].append("an order fails the program's size or spread eligibility")
        else:
            groups[order["score_side"]].append((distance, size))
    q_one = side_score(spread, groups["one"])
    q_two = side_score(spread, groups["two"])
    my_q = min_score(q_one, q_two, midpoint)
    total = _positive(inputs, "snapshot_total_min_score")
    if total < my_q:
        raise ValueError("total snapshot score must include this account's score")
    pool = _num(inputs, "reward_pool_usdc", low=0)
    _positive(inputs, "reward_window_seconds")
    loss = _num(inputs, "assumed_trading_loss_usdc", low=0)
    hypothetical = pool * my_q / total
    result["analysis"].update(q_one=q_one, q_two=q_two, account_min_score=my_q,
                               snapshot_share=my_q / total, conditional_pool_share_usdc=hypothetical,
                               conditional_net_after_assumed_loss=hypothetical - loss,
                               limitation="Order sizes are the resting orders' share sizes. One snapshot is not period-normalized reward share. Cash estimate assumes this share persists for the whole pool; no payout guarantee.")
    if my_q <= 0:
        result["reasons"].append("no positive qualifying liquidity score")
    if hypothetical <= loss:
        result["reasons"].append("conditional reward does not cover the supplied trading-loss assumption")


def _sportsbook(inputs, now, result):
    _true(inputs, "same_event_reviewed")
    _true(inputs, "settlement_rules_match")
    _text(inputs["sportsbook_source"], "sportsbook_source")
    stamp = _past(inputs, "sportsbook_as_of", inputs["as_of"])
    if now - stamp > _positive(inputs, "max_sportsbook_age_seconds"):
        raise ValueError("sportsbook odds are stale")
    yes = _positive(inputs, "yes_decimal_odds")
    no = _positive(inputs, "no_decimal_odds")
    if min(yes, no) <= 1:
        raise ValueError("decimal odds must exceed one")
    overround = 1 / yes + 1 / no
    probability_yes = (1 / yes) / overround
    uncertainty = _num(inputs, "sportsbook_probability_uncertainty", low=0, high=1)
    fair = probability_yes if inputs["outcome"] == "YES" else 1 - probability_yes
    result["analysis"].update(sportsbook_overround=overround - 1, no_vig_probability_yes=probability_yes,
                               no_vig_method="proportional normalization of this complementary binary pair")
    _quotes(inputs, now, result, fair)
    decision = result["analysis"]
    if min(decision["bid_edge_after_fee_and_adverse_selection"],
           decision["ask_edge_after_fee_and_adverse_selection"]) - uncertainty < inputs["min_edge"]:
        result["reasons"].append("sportsbook model uncertainty consumes a quoting side's required edge")


def _copy(inputs, now, result):
    _true(inputs, "history_complete_reviewed")
    _true(inputs, "open_and_closed_positions_included")
    wallet = _text(inputs["selected_wallet"], "selected_wallet")
    market_id = _text(inputs["target_market_id"], "target_market_id")
    event_id = _text(inputs["target_event_id"], "target_event_id")
    _true(inputs, "target_identity_reviewed")
    if inputs["contract"]["market_id"] != market_id or inputs["contract"]["event_id"] != event_id:
        raise ValueError("reviewed contract IDs do not match the selected target market and event")
    selection = _past(inputs, "selection_fixed_at", now)
    trades = _trade_rows(inputs["training_trades"], selection)
    positions = _records(inputs["training_positions"], selection, time_field="observed_at")
    for row in trades + positions + [_object(inputs["target_trade"], "target_trade")]:
        if row["wallet"] != wallet:
            raise ValueError("all training and target records must belong to selected_wallet")
    events = set()
    for position in positions:
        _num(position, "total_pnl")
        if position["status"] not in ("OPEN", "CLOSED", "MIXED"):
            raise ValueError("aggregated position status must be OPEN, CLOSED or MIXED")
        event = _text(position["event"], "position.event")
        if event in events:
            raise ValueError("training positions must aggregate each event once")
        events.add(event)
    target = inputs["target_trade"]
    _trade_rows([target], inputs["as_of"])
    if not selection < target["timestamp"]:
        raise ValueError("wallet selection must be fixed before the target trade")
    if target["side"] != "BUY" or target["outcome"] != inputs["outcome"]:
        raise ValueError("copy screen requires a matching BUY outcome")
    if target["market_id"] != market_id or target["event"] != event_id:
        raise ValueError("target trade does not belong to the selected target market and event")
    if target["target_yes_definition"] != inputs["target_yes_definition"] or target["resolution_source"] != inputs["resolution_source"]:
        raise ValueError("target trade does not match the reviewed contract definition and source")
    _fresh_quote(inputs, now)
    size = _positive(inputs, "copy_size")
    depth = _num(inputs, "available_depth", low=0)
    target_cost = target["cash_notional_usdc"] / target["size"]
    premium = inputs["limit_price"] + inputs["fee_per_share"] - target_cost
    threshold = _num(inputs, "max_copy_price_premium", low=0)
    # The audit's size*price field is its cash weighting, not an exposure input.
    cash_weighted_trades = [{**row, "size": row["cash_notional_usdc"] / row["price"]} for row in trades]
    result["analysis"].update(training_audit=audit(cash_weighted_trades, positions), observed_delay_seconds=now - target["timestamp"],
                               follower_cost_premium_per_share=premium,
                               target_actual_cost_per_share=target_cost,
                               selected_wallet=wallet, target_market_id=market_id, target_event_id=event_id,
                               limitation="Copyability screen only; selected wallet profit is not a future probability or evidence of skill.")
    if depth < size:
        result["reasons"].append("available depth does not cover copy_size")
    if premium > threshold:
        result["reasons"].append("follower cost premium exceeds the preselected threshold")


def _flow(inputs, now, result):
    wallet = _text(inputs["wallet_label"], "wallet_label")
    _text(inputs["economic_direction_definition"], "economic_direction_definition")
    mappings = inputs["condition_mappings"]
    if not isinstance(mappings, list) or not mappings or not all(isinstance(mapping, dict) for mapping in mappings):
        raise ValueError("flow requires explicit reviewed condition mappings, each an object")
    conditions = {}
    for mapping in mappings:
        condition = _text(mapping["condition_id"], "condition_id")
        if condition in conditions:
            raise ValueError("condition mappings must be unique")
        _true(mapping, "reviewed")
        _text(mapping["event"], "event")
        _text(mapping["theme"], "theme")
        if mapping["yes_direction"] not in ("POSITIVE", "NEGATIVE"):
            raise ValueError("YES economic direction must be POSITIVE or NEGATIVE")
        conditions[condition] = mapping
    created = _past(inputs, "wallet_created_at", inputs["as_of"])
    age_hours = (now - created) / 3600
    trades = _trade_rows(inputs["trades"], inputs["as_of"])
    if trades[0]["timestamp"] < created:
        raise ValueError("wallet trades cannot predate wallet creation")
    lookback = _positive(inputs, "lookback_seconds")
    if trades[0]["timestamp"] < now - lookback:
        raise ValueError("flow history extends outside the declared observation window")
    themes, net_changes = {}, {}
    total = 0.0
    share_flow = 0.0
    for trade in trades:
        if trade["wallet"] != wallet:
            raise ValueError("all flow records must belong to wallet_label")
        theme = _text(trade["theme"], "theme")
        mapping = conditions.get(_text(trade["condition_id"], "condition_id"))
        if mapping is None or mapping["event"] != trade["event"] or mapping["theme"] != theme:
            raise ValueError("trade condition, event and theme must match a reviewed mapping")
        if trade["outcome"] not in ("YES", "NO"):
            raise ValueError("flow trade outcome must be YES or NO")
        dollars = trade["cash_notional_usdc"]
        themes[theme] = themes.get(theme, 0) + dollars
        sign = 1 if trade["outcome"] == "YES" else -1
        sign *= 1 if trade["side"] == "BUY" else -1
        sign *= 1 if mapping["yes_direction"] == "POSITIVE" else -1
        condition = trade["condition_id"]
        net_changes[condition] = net_changes.get(condition, 0) + sign * trade["size"]
        share_flow += trade["size"]
        total += dollars
    if not math.isfinite(total) or not math.isfinite(share_flow) or total <= 0:
        raise ValueError("flow notional must be positive and finite")
    positive = sum(max(0, change) for change in net_changes.values())
    negative = sum(max(0, -change) for change in net_changes.values())
    theme_share = max(themes.values()) / total
    direction_share = max(positive, negative) / share_flow
    minimum = _num(inputs, "min_theme_share", low=0, high=1)
    direction_minimum = _num(inputs, "min_direction_share", low=0, high=1)
    checks = (age_hours <= _positive(inputs, "max_wallet_age_hours"),
              total >= _positive(inputs, "min_notional_usdc"), theme_share >= minimum,
              direction_share >= direction_minimum)
    result["analysis"].update(wallet_age_hours=age_hours, observed_notional_usdc=total,
                               dominant_theme_share=theme_share, dominant_direction_share=direction_share,
                               net_positive_share_change=positive, net_negative_share_change=negative,
                               observed_share_flow=share_flow,
                               economic_direction_definition=inputs["economic_direction_definition"],
                               anomaly_alert=all(checks),
                               limitation="Direction nets BUY/SELL YES/NO shares per reviewed condition, then divides the dominant net change by all observed shares traded (observed_share_flow, BUYs plus SELLs). Unobserved positions, other wallets and external hedges remain unknown. This does not identify an insider, establish misconduct or justify a copied trade.")
    if not all(checks):
        result["reasons"].append("observed flow does not meet every preselected alert threshold")


def analyze(index: int, inputs: dict, *, now: float) -> dict:
    """Validate the indexed schema and return a decision, proposal or monitoring result."""
    result = {"eligible": False, "reasons": [], "analysis": {}}
    try:
        if type(index) is not int or index not in SUPPORTED:
            raise ValueError("unsupported signal strategy index")
        _envelope(inputs, now, index)
        if index in (15, 34):
            _news(index, inputs, now, result)
        elif index == 16:
            _fade(inputs, now, result)
        elif index == 17:
            _macro(inputs, now, result)
        elif index == 18:
            _attention(inputs, now, result)
        elif index in (22, 23):
            _latency(index, inputs, now, result)
        elif index == 24:
            _scalp(inputs, now, result)
        elif index == 25:
            _rules(inputs, now, result)
        elif index == 26:
            _dispute(inputs, now, result)
        elif index == 27:
            _quotes(inputs, now, result, _num(inputs, "fair_outcome_probability", low=0, high=1))
        elif index == 28:
            _rewards(inputs, now, result)
        elif index == 29:
            _sportsbook(inputs, now, result)
        elif index == 30:
            _copy(inputs, now, result)
        elif index == 31:
            _flow(inputs, now, result)
        # Derived finite checks also cover overflow of otherwise finite inputs.
        def finite(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("derived analysis contains a non-finite value")
            if isinstance(value, dict):
                for item in value.values():
                    finite(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    finite(item)
        finite(result["analysis"])
        if index == 26:
            # Only a passed pass/fail screen may report true; a monitor has none.
            result.update(eligible=None, decision_screen="none: this resolution monitor reports phase and timing only, "
                                                         "so eligible is null, not a trade signal")
        else:
            result["eligible"] = not result["reasons"]
        if not result["eligible"]:
            result.pop("forecast", None)
    except KeyError as error:
        result["reasons"].append(f"missing required field: {error.args[0]}")
        result.pop("forecast", None)
        result["analysis"] = {}
    except (ValueError, OverflowError, ArithmeticError) as error:  # a TypeError is a code fault and propagates
        result["reasons"].append(str(error))
        result.pop("forecast", None)
        result["analysis"] = {}
    return result


def demo_inputs(index: int, now: float) -> dict:
    """Complete made-up input schemas. Replace every observation before real use.

    Quoting fees are conservative reader estimates, not assumed zero maker fees.
    Reward score sides follow the program's complementary groups: one = YES bids
    plus NO asks; two = YES asks plus NO bids. They are not merely BUY/SELL labels.
    Wallet records use synthetic labels, trade IDs and event-level aggregates.
    Sizes, quantities and depth are share counts; reward order sizes are the resting
    orders' sizes, exactly as the program scores them. Entry fee fields are the cash
    fee per share paid on top of the price; exit fee fields are the cash fee per
    share taken from the proceeds. Wallet records include ``cash_notional_usdc`` in
    dollars: size times price, plus the fee for a BUY if you know it. Condition
    directions describe a reviewed economic thesis, not just BUY/SELL labels.
    Copy wallet and target market/event IDs are exact reviewed bindings.
    """
    if type(index) is not int or index not in SUPPORTED:
        raise ValueError("unsupported signal strategy index")
    _number(now, "now", low=1000)
    yes_definition = "Synthetic event meets the reviewed YES condition by its deadline."
    source = "https://example.invalid/official-result"
    inputs = {"target_yes_definition": yes_definition, "resolution_source": source,
              "evidence": "Synthetic observations for this demonstration only.",
              "source_notes": "Made-up data; replace with independently reviewed observations.",
              "as_of": now - 1, "valid_until": now + 900,
              "contract": {"yes_definition": yes_definition, "resolution_source": source, "end_time": now + 86400},
              "outcome": "YES", "limit_price": .50, "fee_per_share": .01, "min_edge": .02}
    if index in (15, 16, 17, 18, 25, 34):
        inputs.update(probability_yes=.75, conservative_low_yes=.65, conservative_high_yes=.85)
    report = {"url": "https://example.invalid/public-announcement", "summary": "Made-up public announcement.",
              "archive_sha256": "a" * 64, "publicly_accessible": True, "provenance_reviewed": True,
              "published_at": now - 120, "received_at": now - 100}
    if index in (15, 34):
        inputs.update(report=report, report_matches_contract_reviewed=True)
        if index == 34:
            inputs.update(duty_restricted=False, can_influence_outcome=False)
    elif index == 16:
        inputs.update(outcome="NO", pre_news_yes=.40, spike_yes=.80, limit_price=.20,
                      mode="held_to_resolution", resolution_forecast_reviewed=True,
                      probability_yes=.40, conservative_low_yes=.30, conservative_high_yes=.50)
    elif index == 17:
        inputs.update(release_at=now - 60, benchmark_fixed_at=now - 600, actual_received_at=now - 45,
                      actual=3.5, consensus=3.0, surprise_scale=.25, release_units="percentage points",
                      contract_response_model_reviewed=True)
    elif index == 18:
        inputs.update(attention_model_reviewed=True, min_rate_ratio=2,
                      baseline_period={"start": now - 721, "end": now - 361, "count": 100},
                      current_period={"start": now - 361, "end": now - 1, "count": 300})
    elif index in (22, 23):
        inputs.update(reference_matches_contract=True, observation_confirmed=True,
                      event_at=now - 5, feed_received_at=now - 3, quote_at=now - 2,
                      max_quote_age_seconds=5, execution_latency_seconds=1,
                      clock_uncertainty_seconds=.25, opportunity_expires_at=now + 5,
                      conservative_outcome_probability=.70)
        if index == 23:
            inputs["sports_order_delay_seconds"] = 2
    elif index == 24:
        inputs.update(entry_ask=.50, planned_exit_bid=.56, exit_fee_per_share=.01, slippage_reserve=.005,
                      quantity=10, entry_depth=20, exit_depth_estimate=20, quote_at=now - 2,
                      max_quote_age_seconds=5, exit_deadline=now + 30, max_holding_seconds=60)
    elif index == 25:
        report["source_id"] = source
        inputs.update(source_document=report, contract_status="open",
                      rule_review={key: True for key in ("source_match", "timezone", "units", "cutoff", "ties", "exceptions")})
    elif index == 26:
        inputs.update(phase="proposed", proposal_at=now - 300, challenge_deadline=now + 600,
                      settlement_eta=now + 3600, status_source="Synthetic oracle status observation.")
    elif index in (27, 29):
        inputs.update(fair_outcome_probability=.50, half_spread=.07, inventory=20, target_inventory=10,
                      max_inventory=50, inventory_price_per_share=.001, bid_size=5, ask_size=5,
                      tick_size=.01, best_bid=.45, best_ask=.55, quote_at=now - 2, max_quote_age_seconds=5,
                      bid_fill_fee_per_share=.01, ask_fill_fee_per_share=.01, adverse_selection_per_fill=.01)
        if index == 29:
            inputs.update(same_event_reviewed=True, settlement_rules_match=True,
                          sportsbook_source="https://example.invalid/sportsbook", sportsbook_as_of=now - 2,
                          max_sportsbook_age_seconds=5, yes_decimal_odds=1.91, no_decimal_odds=1.91,
                          sportsbook_probability_uncertainty=.01)
    elif index == 28:
        inputs.update(program_active=True, rewards_eligible=True, minimum_size=5, max_spread_cents=3,
                      size_adjusted_midpoint=.50,
                      orders=[{"id": "one", "score_side": "one", "spread_cents": 1, "size": 10},
                              {"id": "two", "score_side": "two", "spread_cents": 1, "size": 10}],
                      snapshot_total_min_score=100, reward_pool_usdc=100, reward_window_seconds=86400,
                      assumed_trading_loss_usdc=1)
    elif index == 30:
        inputs["contract"].update(market_id="synthetic-market-2", event_id="event-2")
        inputs.update(history_complete_reviewed=True, open_and_closed_positions_included=True,
                      selected_wallet="Synthetic Wallet A", target_market_id="synthetic-market-2",
                      target_event_id="event-2", target_identity_reviewed=True,
                      selection_fixed_at=now - 120,
                      training_trades=[{"id": "training-1", "timestamp": now - 300, "event": "event-1", "wallet": "Synthetic Wallet A", "side": "BUY", "size": 10, "price": .40, "cash_notional_usdc": 4}],
                      training_positions=[{"id": "position-1", "observed_at": now - 240, "event": "event-1", "wallet": "Synthetic Wallet A", "status": "CLOSED", "total_pnl": 6},
                                          {"id": "position-2", "observed_at": now - 240, "event": "event-3", "wallet": "Synthetic Wallet A", "status": "OPEN", "total_pnl": -3}],
                      target_trade={"id": "target-1", "timestamp": now - 60, "event": "event-2", "market_id": "synthetic-market-2", "wallet": "Synthetic Wallet A", "side": "BUY", "size": 10, "price": .49, "cash_notional_usdc": 4.9, "outcome": "YES",
                                    "target_yes_definition": yes_definition, "resolution_source": source},
                      quote_at=now - 2, max_quote_age_seconds=5, copy_size=5, available_depth=10, max_copy_price_premium=.03)
    elif index == 31:
        inputs.update(wallet_label="Synthetic Wallet A", wallet_created_at=now - 600,
                      economic_direction_definition="Greater likelihood of the synthetic economic thesis.",
                      condition_mappings=[{"condition_id": "condition-1", "event": "event-1", "theme": "synthetic-theme", "yes_direction": "POSITIVE", "reviewed": True},
                                          {"condition_id": "condition-2", "event": "event-2", "theme": "synthetic-theme", "yes_direction": "POSITIVE", "reviewed": True}],
                      lookback_seconds=600, max_wallet_age_hours=24, min_notional_usdc=100,
                      min_theme_share=.80, min_direction_share=.90,
                      trades=[{"id": "flow-1", "timestamp": now - 500, "event": "event-1", "condition_id": "condition-1", "wallet": "Synthetic Wallet A", "theme": "synthetic-theme", "outcome": "YES", "side": "BUY", "size": 400, "price": .50, "cash_notional_usdc": 200},
                              {"id": "flow-2", "timestamp": now - 400, "event": "event-2", "condition_id": "condition-2", "wallet": "Synthetic Wallet A", "theme": "synthetic-theme", "outcome": "YES", "side": "BUY", "size": 400, "price": .50, "cash_notional_usdc": 200}])
    return inputs
