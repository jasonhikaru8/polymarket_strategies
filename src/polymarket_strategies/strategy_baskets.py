"""Snapshot decision tools for strategies 1–6, 9 and 21; never submit orders.

Start with ``demo_inputs(index, now)`` for the complete JSON schema. Common fields:
``as_of``, ``valid_until``, ``shares``, ``max_cash``, ``min_profit`` and ``review``.
Review flags are the reader's recorded checks, not machine verification of prose.
Each leg names its market, YES/NO outcome, definition, source and cutoff; its book
is best-first ``[[price, shares], ...]`` with its own timestamp, an explicit fee
schedule and ``fee_collection: "cash"``. Every fee is cash: a BUY leg pays price
plus fee per share and receives every matched share; a SELL leg receives price
minus fee per share. A leg on another venue states that venue's fee the same way
(schedule plus ``flat_per_share``). ``shares`` is the order quantity per leg.
``slippage_per_share`` reserves extra costs in quote currency. Fees are modeled
per displayed level, without crediting rebates or promising exact rounding.
Fees: https://docs.polymarket.com/trading/fees

A4 additionally requires a matching ``underlying_event_id`` on both legs: a
reader-verified identifier for the same event criterion across dates, even when
Gamma ``event_id`` values differ; the legs' definitions differ by date and are
reported. C10 requires one matching ``launch_id`` naming the same token and
qualifying launch, and matching ``event_id`` for the reviewed ladder; rung
definitions differ by threshold and are reported. Similar wording, sources and
review checkboxes cannot replace these subject identities.

A1: BUY a binary set, or model minting then SELLing it. A2: exact-universe YES/NO
bundles, or buy one NO then convert and sell the other YES tokens. A3/A4: acquire
larger/later YES plus smaller/earlier NO. A5: buy opposite outcomes on two venues,
stress disagreeing resolutions, conversion and funding. A6: evaluate maker bids,
observed inventory and an independently estimated completion rate. C4: value an
exclusive selected-tail basket against a conservative coverage probability. C10:
multiply launch and conditional FDV probabilities, and inspect nested rungs.

Books describe possible depth, not simultaneous fills. All multi-leg execution,
conversion, venue access and contract interpretation remain reader responsibilities.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations
from math import isfinite

from .fees import FeeSchedule, fee_per_share


INDICES = {1, 2, 3, 4, 5, 6, 9, 21}


def _number(value, name, *, low=0.0, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):  # a numeric string is not a number here, as in the model and signal tools
        raise ValueError(f"{name} must be a finite number")
    try:
        value = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not isfinite(value) or value < low or (high is not None and value > high):
        raise ValueError(f"{name} is outside its permitted range")
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value


def _review(inputs, *flags):
    checks = inputs.get("review", {})
    if not isinstance(checks, dict) or any(checks.get(flag) is not True for flag in flags):
        raise ValueError("review required: " + ", ".join(flags))


def _fresh(as_of, valid_until, now, max_age):
    stamp = _number(as_of, "as_of")
    expiry = _number(valid_until, "valid_until")
    if stamp > now or now - stamp > max_age or not now < expiry:
        raise ValueError("snapshot or forecast is stale, future-dated or expired")


def _common(inputs, now):
    now = _number(now, "now")
    age = _number(inputs.get("max_age_seconds", 60), "max_age_seconds", low=1, high=120)
    _fresh(inputs.get("as_of"), inputs.get("valid_until"), now, age)
    _review(inputs, "rules", "source", "timing")
    quantity = _number(inputs.get("shares"), "shares", low=1e-12)
    cash = _number(inputs.get("max_cash"), "max_cash")
    minimum = _number(inputs.get("min_profit", 0), "min_profit")
    return quantity, cash, minimum, age


def _leg(leg, now, max_age):
    for key in ("market_id", "definition", "source"):
        _text(leg.get(key), key)
    if leg.get("outcome") not in ("YES", "NO"):
        raise ValueError("leg outcome must be YES or NO")
    if _number(leg.get("cutoff"), "cutoff") <= now:
        raise ValueError("contract cutoff has passed")
    _fresh(leg.get("as_of"), leg.get("valid_until"), now, max_age)
    fee = leg.get("fee")
    if not isinstance(fee, dict) or type(fee.get("taker_only")) is not bool:
        raise ValueError("each leg needs an explicit fee schedule")
    schedule = FeeSchedule(_number(fee.get("rate"), "fee rate"),
                           _number(fee.get("exponent"), "fee exponent"),
                           taker_only=fee["taker_only"])
    slip = _number(leg.get("slippage_per_share", 0), "slippage_per_share")
    if leg.get("fee_collection") != "cash":
        raise ValueError("fee_collection must be cash: a BUY pays its fee on top of the price "
                         "and receives every matched share; a SELL fee comes out of the proceeds")
    return schedule, slip


def _fill(leg, quantity, now, max_age, *, sell=False):
    schedule, slip = _leg(leg, now, max_age)
    minimum = _number(leg.get("min_size"), "min_size", low=1e-12)
    levels = leg.get("book")
    if not isinstance(levels, list) or not levels:
        raise ValueError("each traded leg needs nonempty displayed depth")
    checked = []
    for level in levels:
        if not isinstance(level, (list, tuple)) or len(level) != 2:
            raise ValueError("book levels must be [price, shares]")
        checked.append((_number(level[0], "book price", low=1e-12, high=1 - 1e-12),
                        _number(level[1], "book shares", low=1e-12)))
    prices = [price for price, _ in checked]
    if prices != sorted(prices, reverse=sell):
        raise ValueError("book must be ordered best price first")
    remaining = quantity
    gross = fees = 0.0
    fills = []
    for price, available in checked:
        size = min(remaining, available)
        if size <= 0:
            break
        fee = size * (fee_per_share(price, schedule)
                      + _number(leg["fee"].get("flat_per_share", 0), "flat_per_share"))
        gross += size * price
        fees += fee
        fills.append({"price": price, "shares": size, "modeled_fee": fee})
        remaining -= size
    filled = quantity - remaining
    conversion = _number(leg.get("usd_per_unit", 1), "usd_per_unit", low=1e-12)
    # Cash fees: a BUY pays them on top of the price, a SELL receives its proceeds net of them.
    total = (gross - fees - filled * slip if sell else gross + fees + filled * slip) * conversion
    return {"market_id": leg["market_id"], "outcome": leg["outcome"],
            "action": "SELL" if sell else "BUY", "requested_shares": quantity,
            "displayed_fill_shares": filled, "available_shares": sum(size for _, size in checked),
            "minimum_shares": minimum, "depth_sufficient": remaining <= 1e-9 and quantity >= minimum,
            "gross_usd": gross * conversion, "modeled_fees_usd": fees * conversion,
            "slippage_reserve_usd": filled * slip * conversion,
            "modeled_net_usd": total, "fills": fills}


def _same(legs, *fields):
    if any(leg.get(field) != legs[0].get(field) for field in fields for leg in legs):
        raise ValueError("contracts do not match on " + ", ".join(fields))


def _universe(inputs):
    universe = inputs.get("universe")
    if (not isinstance(universe, list) or len(universe) < 2
            or any(not isinstance(item, str) or not item.strip() for item in universe)
            or len(set(universe)) != len(universe)):
        raise ValueError("universe must list at least two distinct outcome identifiers")
    return universe


def _result(analysis, reasons):
    def finite(value):
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("calculation exceeded finite numeric range")
        if isinstance(value, dict):
            for child in value.values():
                finite(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                finite(child)
    finite(analysis)
    return {"eligible": not reasons, "reasons": reasons, "analysis": analysis}


def _basket(inputs, legs, scenarios, quantity, cash, minimum, now, age, *, fixed_cost=0):
    fills = [_fill(leg, quantity, now, age) for leg in legs]
    cost = sum(fill["modeled_net_usd"] for fill in fills) + fixed_cost
    rows = [{"ending": name,
             "payout_usd": sum(payout * fill["displayed_fill_shares"] for payout, fill in zip(payouts, fills, strict=True)),
             "profit_usd": sum(payout * fill["displayed_fill_shares"] for payout, fill in zip(payouts, fills, strict=True)) - cost}
            for name, payouts in scenarios]
    floor = min(row["profit_usd"] for row in rows)
    reasons = []
    if not all(fill["depth_sufficient"] for fill in fills):
        reasons.append("not enough depth or order size on every leg for the requested basket")
    if cost > cash + 1e-9:
        reasons.append("modeled cost exceeds max_cash")
    analysis = {"legs": fills, "modeled_cost_usd": cost, "payout_scenarios": rows,
                "floor_profit_usd": floor, "quantity": quantity,
                "worst_single_leg_loss_usd": max(fill["modeled_net_usd"] for fill in fills),
                "execution_risk": "Separate legs can fill unevenly; displayed depth is not a fill promise."}
    return analysis, reasons


def _binary(index, inputs, quantity, cash, minimum, now, age):
    legs = inputs.get("legs", [])
    if not isinstance(legs, list) or len(legs) != 2:
        raise ValueError("this strategy needs exactly two legs")
    if index == 1:
        _review(inputs, "binary_complete_set")
        _same(legs, "market_id", "source", "cutoff", "definition")
        if (legs[0].get("outcome"), legs[1].get("outcome")) not in (("YES", "NO"), ("NO", "YES")):
            raise ValueError("binary parity needs one YES and one NO from the same market")
        mode = inputs.get("mode", "buy_set")
        if mode == "mint_sell_set":
            _review(inputs, "mint_route", "inventory_and_collateral")
            fills = [_fill(leg, quantity, now, age, sell=True) for leg in legs]
            fixed = _number(inputs.get("conversion_cost_usd"), "conversion_cost_usd")
            capital = quantity + fixed
            profit = sum(fill["modeled_net_usd"] for fill in fills) - capital
            reasons = []
            if capital > cash:
                reasons.append("mint collateral and conversion cost exceed max_cash")
            if not all(fill["depth_sufficient"] for fill in fills):
                reasons.append("insufficient depth or order size to sell the whole set")
            if profit <= minimum + 1e-12:
                reasons.append("mint-and-sell profit does not exceed min_profit")
            return _result({"legs": fills, "collateral_required_usd": capital,
                            "modeled_profit_usd": profit,
                            "unsold_token_shares": [quantity - fill["displayed_fill_shares"] for fill in fills],
                            "maximum_collateral_loss_usd": capital,
                            "execution_risk": "Minting and separate sales are not atomic; unsold inventory remains."}, reasons)
        if mode != "buy_set":
            raise ValueError("A1 mode must be buy_set or mint_sell_set")
        scenarios = [(f"{winner} wins", [float(leg["outcome"] == winner) for leg in legs]) for winner in ("YES", "NO")]
    else:
        _review(inputs, "implication")
        if [leg.get("outcome") for leg in legs] != ["YES", "NO"]:
            raise ValueError("legs must be larger/later YES, then smaller/earlier NO")
        if legs[0].get("market_id") == legs[1].get("market_id"):
            raise ValueError("nested contracts must be different markets")
        _same(legs, "source")
        if index == 4:
            _review(inputs, "same_event", "deadline_nesting")
            for leg in legs:
                _text(leg.get("underlying_event_id"), "underlying_event_id")
            # The rungs' definitions differ by date; the reviewed event identity must not.
            _same(legs, "underlying_event_id")
            if _number(legs[1].get("cutoff"), "earlier cutoff") >= _number(legs[0].get("cutoff"), "later cutoff"):
                raise ValueError("earlier cutoff must precede later cutoff")
        else:
            _same(legs, "cutoff")
            _text(inputs.get("implication_evidence"), "implication_evidence")
        scenarios = [("both YES", [1, 0]), ("larger YES, smaller NO", [1, 1]),
                     ("both NO", [0, 1])]
    analysis, reasons = _basket(inputs, legs, scenarios, quantity, cash, minimum, now, age,
                                fixed_cost=_number(inputs.get("conversion_cost_usd", 0), "conversion_cost_usd"))
    analysis["excluded_ending"] = "smaller YES/larger NO is excluded only by the reviewed implication" if index != 1 else None
    analysis["leg_definitions"] = [leg["definition"] for leg in legs]
    if analysis["floor_profit_usd"] <= minimum + 1e-12:
        reasons.append("reviewed payoff floor does not exceed cost plus min_profit")
    return _result(analysis, reasons)


def _negrisk(inputs, quantity, cash, minimum, now, age):
    _review(inputs, "universe_complete", "exclusive", "exhaustive", "fixed_outcomes", "negrisk_link")
    universe = _universe(inputs)
    mode = inputs.get("mode", "buy_yes_bundle")
    legs = inputs.get("legs", [])
    if not isinstance(legs, list) or len(legs) != len(universe):
        raise ValueError("NegRisk legs must cover the full outcome universe")
    ids = [_text(leg.get("market_id"), "market_id") for leg in legs]
    if len(set(ids)) != len(ids) or set(ids) != set(universe):
        raise ValueError("missing, duplicate or extra NegRisk outcome")
    _same(legs, "event_id", "source", "cutoff")
    _text(legs[0].get("event_id"), "event_id")
    fixed = _number(inputs.get("conversion_cost_usd", 0), "conversion_cost_usd")
    if mode == "convert_no":
        _review(inputs, "conversion_route", "inventory_and_collateral")
        source_id = _text(inputs.get("source_outcome"), "source_outcome")
        if source_id not in universe:
            raise ValueError("source_outcome is outside the reviewed universe")
        source = next(leg for leg in legs if leg["market_id"] == source_id)
        others = [leg for leg in legs if leg["market_id"] != source_id]
        if source.get("outcome") != "NO" or any(leg.get("outcome") != "YES" for leg in others):
            raise ValueError("conversion buys source NO and sells every other YES")
        buy = _fill(source, quantity, now, age)
        sells = [_fill(leg, buy["displayed_fill_shares"], now, age, sell=True) for leg in others]
        capital = buy["modeled_net_usd"] + fixed
        profit = sum(leg["modeled_net_usd"] for leg in sells) - capital
        reasons = []
        if not all(fill["depth_sufficient"] for fill in [buy, *sells]):
            reasons.append("conversion route lacks full requested depth or order size")
        if capital > cash:
            reasons.append("NO purchase and conversion cost exceed max_cash")
        if profit <= minimum + 1e-12:
            reasons.append("conversion profit does not exceed min_profit")
        return _result({"legs": [buy, *sells], "conversion_cost_usd": fixed,
                        "cash_required_usd": capital, "modeled_profit_usd": profit,
                        "maximum_unhedged_no_purchase_loss_usd": capital,
                        "execution_risk": "Only NO-to-other-YES conversion is modeled; unsold converted tokens carry risk."}, reasons)
    outcome = {"buy_yes_bundle": "YES", "buy_no_bundle": "NO"}.get(mode) if isinstance(mode, str) else None
    if outcome is None or any(leg.get("outcome") != outcome for leg in legs):
        raise ValueError("bundle mode must match all YES or all NO legs")
    scenarios = [(winner, [float((leg["market_id"] == winner) == (outcome == "YES")) for leg in legs])
                 for winner in universe]
    analysis, reasons = _basket(inputs, legs, scenarios, quantity, cash, minimum, now, age, fixed_cost=fixed)
    if analysis["floor_profit_usd"] <= minimum + 1e-12:
        reasons.append("exact-universe bundle has no positive net floor above min_profit")
    return _result(analysis, reasons)


def _crossvenue(inputs, quantity, cash, minimum, now, age):
    _review(inputs, "equivalence", "void_rules", "payout_timing", "access", "currency", "costs")
    legs = inputs.get("legs", [])
    if not isinstance(legs, list) or len(legs) != 2 or [leg.get("outcome") for leg in legs] != ["YES", "NO"]:
        raise ValueError("cross-venue legs must be venue A YES, then venue B NO")
    if len({_text(leg.get("venue"), "venue") for leg in legs}) != 2:
        raise ValueError("A5 needs two distinct venues")
    _same(legs, "source", "cutoff", "definition")
    payout = [_number(leg.get("payout_usd_floor"), "payout_usd_floor", low=1e-12,
                      high=_number(leg.get("usd_per_unit"), "usd_per_unit", low=1e-12)) for leg in legs]
    harm = _number(inputs.get("harmful_mismatch_probability_upper"), "harmful mismatch probability", high=1)
    benefit = _number(inputs.get("beneficial_mismatch_probability_lower", 0), "beneficial mismatch probability", high=1)
    if harm + benefit > 1:
        raise ValueError("mismatch probabilities exceed one")
    _text(inputs.get("mismatch_evidence"), "mismatch_evidence")
    fixed = _number(inputs.get("funding_and_withdrawal_usd"), "funding_and_withdrawal_usd")
    days = _number(inputs.get("maximum_lock_days"), "maximum_lock_days", low=1e-12)
    if days * 86400 < _number(legs[0].get("cutoff"), "cutoff") - now:
        raise ValueError("maximum_lock_days is shorter than the contract horizon")
    annual = _number(inputs.get("funding_annual_rate"), "funding_annual_rate", high=1)  # a fraction: 0.04 is 4%
    scenarios = [("both YES", [payout[0], 0]), ("both NO", [0, payout[1]]),
                 ("harmful disagreement", [0, 0]), ("beneficial disagreement", payout)]
    analysis, reasons = _basket(inputs, legs, scenarios, quantity, cash, minimum, now, age, fixed_cost=fixed)
    financing = analysis["modeled_cost_usd"] * annual * days / 365
    cost = analysis["modeled_cost_usd"] + financing
    for row in analysis["payout_scenarios"]:
        row["profit_usd"] -= financing
    held_payout = [value * fill["displayed_fill_shares"] for value, fill in zip(payout, analysis["legs"])]
    expected_payout = (1 - harm - benefit) * min(held_payout) + benefit * sum(held_payout)
    expected = expected_payout - cost
    if cost > cash + 1e-9 and "modeled cost exceeds max_cash" not in reasons:
        reasons.append("funding-inclusive modeled cost exceeds max_cash")
    if expected <= minimum + 1e-12:
        reasons.append("conservative mismatch-adjusted profit does not exceed min_profit")
    analysis.update(modeled_cost_usd=cost, financing_cost_usd=financing,
                    conservative_expected_profit_usd=expected,
                    matched_resolution_floor_profit_usd=min(held_payout) - cost,
                    floor_profit_usd=-cost, harmful_disagreement_loss_usd=cost,
                    modeled_simple_annual_return=expected / cost * 365 / days if cost else 0,
                    classification="cross-venue scenario estimate; a harmful resolution can lose both legs")
    return _result(analysis, reasons)


def _legged(inputs, quantity, cash, minimum, now, age):
    _review(inputs, "binary_complete_set", "maker_fees", "completion_model", "inventory")
    legs = inputs.get("legs", [])
    if not isinstance(legs, list) or len(legs) != 2 or [leg.get("outcome") for leg in legs] != ["YES", "NO"]:
        raise ValueError("maker legs must be YES then NO")
    _same(legs, "market_id", "source", "cutoff", "definition")
    prices = []
    queues = []
    for leg in legs:
        schedule, slip = _leg(leg, now, age)
        if not schedule.taker_only:
            raise ValueError("maker fee treatment is unknown for a non-taker-only schedule")
        if _number(leg["fee"].get("flat_per_share", 0), "flat_per_share") != 0:
            raise ValueError("A6 does not assume that a flat fee is waived for makers")
        prices.append(_number(leg.get("limit_price"), "maker limit_price", low=1e-12, high=1 - 1e-12) + slip)
        queues.append(_number(leg.get("queue_ahead"), "queue_ahead"))
        if quantity < _number(leg.get("min_size"), "min_size", low=1e-12):
            raise ValueError("maker quantity is below minimum order size")
    rate = _number(inputs.get("completion_probability_lower"), "completion probability", high=1)
    _text(inputs.get("completion_evidence"), "completion_evidence")
    loss = _number(inputs.get("stranded_loss_per_share"), "stranded_loss_per_share")
    maximum = _number(inputs.get("max_stranded_loss_usd"), "max_stranded_loss_usd")
    inventory = inputs.get("inventory", {})
    sizes = [_number(inventory.get(f"{side}_shares"), f"{side}_shares") for side in ("yes", "no")]
    costs = [_number(inventory.get(f"{side}_cost_usd"), f"{side}_cost_usd") for side in ("yes", "no")]
    if any(size == 0 and cost != 0 for size, cost in zip(sizes, costs)):
        raise ValueError("zero inventory cannot have a nonzero acquisition cost")
    paired = min(sizes)
    pair_cost = sum(paired * cost / size if size else 0 for size, cost in zip(sizes, costs))
    edge = 1 - sum(prices)
    expected = quantity * (rate * edge - (1 - rate) * loss)
    budget = quantity * sum(prices)
    orphan_risk = quantity * max(prices)
    reasons = []
    if edge <= 0 or expected <= minimum + 1e-12:
        reasons.append("completed-set edge or conservative completion expectancy is insufficient")
    if budget > cash + 1e-9:
        reasons.append("both maker bids exceed max_cash")
    observed_orphan_cost = sum(costs) - pair_cost
    if orphan_risk + observed_orphan_cost > maximum + 1e-9:
        reasons.append("a full unhedged first fill exceeds max_stranded_loss_usd")
    denominator = edge + loss
    return _result({"maker_limit_prices": prices, "queue_ahead": queues,
                    "full_pair_cost_usd": budget, "completed_profit_per_set": edge,
                    "conservative_expected_profit_usd": expected,
                    "break_even_completion_probability": loss / denominator if denominator > 0 else None,
                    "maximum_first_leg_principal_loss_usd": orphan_risk,
                    "total_unpaired_principal_at_risk_usd": orphan_risk + observed_orphan_cost,
                    "observed_paired_shares": paired, "observed_paired_cost_usd": pair_cost,
                    "observed_pair_payout_profit_usd": paired - pair_cost,
                    "unpaired_yes_shares": sizes[0] - paired, "unpaired_no_shares": sizes[1] - paired,
                    "unpaired_acquisition_cost_usd": sum(costs) - pair_cost,
                    "execution_risk": "Queue size does not predict fills. Estimated rebates are not credited."}, reasons)


def _tails(inputs, quantity, cash, minimum, now, age):
    _review(inputs, "universe_complete", "exclusive", "exhaustive", "forecast")
    universe = _universe(inputs)
    legs = inputs.get("legs", [])
    if not isinstance(legs, list) or len(legs) < 2:
        raise ValueError("tail ladder needs at least two selected buckets")
    ids = [_text(leg.get("market_id"), "market_id") for leg in legs]
    if len(set(ids)) != len(ids) or not set(ids) <= set(universe) or any(leg.get("outcome") != "YES" for leg in legs):
        raise ValueError("tail ladder requires distinct YES buckets from the reviewed universe")
    _same(legs, "event_id", "source", "cutoff")
    _text(legs[0].get("event_id"), "event_id")
    probability = _number(inputs.get("coverage_probability_lower"), "coverage_probability_lower", high=1)
    _text(inputs.get("forecast_evidence"), "forecast_evidence")
    threshold = _number(inputs.get("max_bucket_price", 0.1), "max_bucket_price", low=1e-12, high=1)
    scenarios = [(winner, [float(leg["market_id"] == winner) for leg in legs]) for winner in universe]
    analysis, reasons = _basket(inputs, legs, scenarios, quantity, cash, minimum, now, age)
    cost = analysis["modeled_cost_usd"]
    minimum_received = min(fill["displayed_fill_shares"] for fill in analysis["legs"])
    expected = probability * minimum_received - cost if all(fill["depth_sufficient"] for fill in analysis["legs"]) else None
    if any(fill["fills"] and max(row["price"] for row in fill["fills"]) > threshold for fill in analysis["legs"]):
        reasons.append("selected depth includes prices above max_bucket_price")
    if expected is not None and expected <= minimum + 1e-12:
        reasons.append("conservative covered-winner probability does not pay for the basket")
    analysis.update(conservative_coverage_probability=probability,
                    break_even_coverage_probability=cost / minimum_received if minimum_received else None,
                    conservative_expected_profit_usd=expected,
                    maximum_loss_usd=cost if set(ids) != set(universe) else max(0, -analysis["floor_profit_usd"]),
                    classification="one directional bet on a covered winner, not independent lotteries")
    return _result(analysis, reasons)


def _fdv(inputs, quantity, cash, minimum, now, age):
    _review(inputs, "launch_definition", "fdv_measurement", "deadline_nesting", "forecast")
    launch = _number(inputs.get("launch_probability"), "launch_probability", high=1)
    launch_low = _number(inputs.get("launch_probability_lower"), "launch_probability_lower", high=launch)
    _text(inputs.get("forecast_evidence"), "forecast_evidence")
    rungs = inputs.get("rungs")
    if not isinstance(rungs, list) or len(rungs) < 2:
        raise ValueError("FDV needs at least two ascending thresholds")
    thresholds = [_number(rung.get("threshold_usd"), "threshold_usd", low=1e-12) for rung in rungs]
    if thresholds != sorted(thresholds) or len(set(thresholds)) != len(thresholds):
        raise ValueError("FDV thresholds must be distinct and ascending")
    probabilities = [_number(rung.get("conditional_probability"), "conditional_probability", high=1) for rung in rungs]
    lower = [_number(rung.get("conditional_probability_lower"), "conditional_probability_lower", high=p)
             for rung, p in zip(rungs, probabilities)]
    if probabilities != sorted(probabilities, reverse=True) or lower != sorted(lower, reverse=True):
        raise ValueError("higher FDV thresholds cannot have greater probabilities")
    legs = [rung.get("leg", {}) for rung in rungs]
    for leg in legs:
        _text(leg.get("launch_id"), "launch_id")
        _text(leg.get("event_id"), "event_id")
    _same(legs, "source", "cutoff", "launch_id", "event_id")  # definitions differ by threshold
    if len({_text(leg.get("market_id"), "market_id") for leg in legs}) != len(legs) or any(leg.get("outcome") != "YES" for leg in legs):
        raise ValueError("FDV rungs need distinct YES markets")
    values = []
    for threshold, p, low, leg in zip(thresholds, probabilities, lower, legs):
        fill = _fill(leg, quantity, now, age)
        cost = fill["modeled_net_usd"]
        conservative = launch_low * low
        expected = fill["displayed_fill_shares"] * conservative - cost
        values.append({"threshold_usd": threshold, "definition": leg["definition"], "conditional_probability": p,
                       "joint_probability": launch * p, "conservative_joint_probability": conservative,
                       "break_even_probability": cost / fill["displayed_fill_shares"] if fill["displayed_fill_shares"] else None,
                       "conservative_expected_profit_usd": expected,
                       "modeled_cost_usd": cost, "eligible": fill["depth_sufficient"] and cost <= cash and expected > minimum + 1e-12,
                       "leg": fill, "no_launch_profit_usd": -cost})
    nested = []
    for low_rung, high_rung in combinations(rungs, 2):
        low_leg = low_rung["leg"]
        high_no = deepcopy(high_rung["leg"])
        high_no["outcome"] = "NO"
        high_no["book"] = high_rung.get("no_book")
        scenarios = [("no launch or below lower threshold", [0, 1]),
                     ("between thresholds", [1, 1]), ("above both thresholds", [1, 0])]
        analysis, reasons = _basket(inputs, [low_leg, high_no], scenarios, quantity, cash, minimum, now, age)
        if analysis["floor_profit_usd"] <= minimum + 1e-12:
            reasons.append("nested FDV pair does not cover its cost above min_profit")
        nested.append({"lower_threshold_usd": low_rung["threshold_usd"],
                       "higher_threshold_usd": high_rung["threshold_usd"],
                       "eligible": not reasons, "reasons": reasons, **analysis})
    reasons = [] if any(row["eligible"] for row in values + nested) else ["no funded-depth rung value or nested pair passes the modeled screen"]
    return _result({"launch_probability": launch, "rung_values": values, "nested_pairs": nested,
                    "execution_risk": "Rungs are correlated. No-launch risk is explicit; conditional forecasts remain reader estimates."}, reasons)


def analyze(index: int, inputs: dict, *, now: float) -> dict:
    """Reject malformed snapshots; return modeled decisions without authentication."""
    try:
        if type(index) is not int or index not in INDICES:
            raise ValueError("unsupported basket strategy index")
        if not isinstance(inputs, dict):
            raise ValueError("inputs must be a JSON object")
        quantity, cash, minimum, age = _common(inputs, now)
        rows = inputs.get("rungs" if index == 21 else "legs", [])
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("legs and rungs must be lists of objects")
        legs = [row.get("leg", {}) for row in rows] if index == 21 else rows
        if not all(isinstance(leg, dict) for leg in legs) or not isinstance(inputs.get("inventory", {}), dict):
            raise ValueError("each leg and the inventory must be an object")
        if index != 5 and any(_number(leg.get("usd_per_unit", 1), "usd_per_unit", low=1e-12) != 1 for leg in legs):
            raise ValueError("only A5 supports non-dollar unit conversion")
        handler = _binary if index in {1, 3, 4} else {2: _negrisk, 5: _crossvenue, 6: _legged, 9: _tails, 21: _fdv}[index]
        args = (index, inputs) if handler is _binary else (inputs,)
        return handler(*args, quantity, cash, minimum, float(now), age)
    # Containers and identity fields are validated explicitly, so a TypeError or AttributeError is a code
    # fault: it propagates instead of being reported as an input problem.
    except (ValueError, KeyError, OverflowError) as error:
        return {"eligible": False, "reasons": [str(error) or "invalid snapshot input"], "analysis": {}}


def demo_inputs(index: int, now: float) -> dict:
    """Synthetic schema examples, deliberately unrelated to any real market/account."""
    if index not in INDICES:
        raise ValueError("unsupported basket strategy index")
    review = {flag: True for flag in ("rules", "source", "timing", "binary_complete_set", "implication",
              "same_event", "deadline_nesting", "universe_complete", "exclusive", "exhaustive", "fixed_outcomes",
              "negrisk_link", "conversion_route", "mint_route", "inventory_and_collateral", "equivalence",
              "void_rules", "payout_timing", "access", "currency", "costs", "maker_fees", "completion_model",
              "inventory", "forecast", "launch_definition", "fdv_measurement")}
    def leg(market, outcome, price):
        return {"market_id": market, "event_id": "synthetic-event", "outcome": outcome,
                "underlying_event_id": "synthetic-underlying-event",
                "definition": "Synthetic reviewed event definition", "source": "https://example.invalid/synthetic",
                "cutoff": now + 30 * 86400, "as_of": now, "valid_until": now + 60,
                "book": [[price, 100]], "min_size": 5, "fee": {"rate": 0.04, "exponent": 1, "taker_only": True},
                "slippage_per_share": 0.001, "fee_collection": "cash"}
    result = {"as_of": now, "valid_until": now + 60, "max_age_seconds": 60,
              "shares": 10, "max_cash": 20, "min_profit": 0, "review": review}
    if index == 1:
        result.update(mode="buy_set", legs=[leg("binary", "YES", 0.45), leg("binary", "NO", 0.48)], conversion_cost_usd=0)
    elif index == 2:
        result.update(mode="buy_yes_bundle", universe=["bucket-a", "bucket-b", "bucket-c"],
                      legs=[leg("bucket-a", "YES", 0.30), leg("bucket-b", "YES", 0.28), leg("bucket-c", "YES", 0.34)],
                      conversion_cost_usd=0)
    elif index in {3, 4}:
        result.update(legs=[leg("larger", "YES", 0.28), leg("smaller", "NO", 0.68)],
                      implication_evidence="Synthetic rules make the smaller event imply the larger event")
        if index == 4:
            result["legs"][0]["definition"] = "Synthetic event happens by the later date"
            result["legs"][1].update(cutoff=now + 15 * 86400, definition="Synthetic event happens by the earlier date")
    elif index == 5:
        result.update(legs=[leg("venue-a-market", "YES", 0.55), leg("venue-b-market", "NO", 0.38)],
                      harmful_mismatch_probability_upper=0.01, beneficial_mismatch_probability_lower=0,
                      mismatch_evidence="Synthetic conservative scenario assumption, not an observed estimate",
                      funding_and_withdrawal_usd=0.01, maximum_lock_days=35, funding_annual_rate=0.04)
        for name, item in zip(("venue-a", "venue-b"), result["legs"]):
            item.update(venue=name, usd_per_unit=1, payout_usd_floor=1)
    elif index == 6:
        result.update(legs=[leg("binary", "YES", 0.46), leg("binary", "NO", 0.49)],
                      completion_probability_lower=0.95, stranded_loss_per_share=0.10,
                      completion_evidence="Synthetic independently estimated fill history", max_stranded_loss_usd=6,
                      inventory={"yes_shares": 7, "no_shares": 5, "yes_cost_usd": 3.22, "no_cost_usd": 2.45})
        for price, item in zip((0.46, 0.49), result["legs"]):
            item.update(limit_price=price, queue_ahead=100)
    elif index == 9:
        result.update(universe=["tail-a", "tail-b", "middle"],
                      legs=[leg("tail-a", "YES", 0.02), leg("tail-b", "YES", 0.03)],
                      coverage_probability_lower=0.15, forecast_evidence="Synthetic independent coverage forecast", max_bucket_price=0.10)
    else:
        result.update(launch_probability=0.6, launch_probability_lower=0.5,
                      forecast_evidence="Synthetic independent launch and conditional valuation forecasts",
                      rungs=[{"threshold_usd": 100_000_000, "conditional_probability": 0.9,
                              "conditional_probability_lower": 0.8, "leg": leg("fdv-low", "YES", 0.30), "no_book": [[0.71, 100]]},
                             {"threshold_usd": 500_000_000, "conditional_probability": 0.6,
                              "conditional_probability_lower": 0.5, "leg": leg("fdv-high", "YES", 0.20), "no_book": [[0.81, 100]]}])
        for rung in result["rungs"]:
            rung["leg"].update(launch_id="synthetic-token-qualifying-launch",
                               definition=f"Synthetic token FDV above ${rung['threshold_usd'] // 1_000_000}M one day after launch")
    return result
