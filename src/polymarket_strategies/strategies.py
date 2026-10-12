"""Legacy and indexed strategy checks using supplied evidence, never invented forecasts.

These checks assume a reviewed binary contract held to resolution. They do not verify
the forecast, comparability, quote freshness, account eligibility or executable fills.
The order workflow must check those separately before submitting any order.
"""
from __future__ import annotations

import math

from .edge_check import wilson_interval


def _number(value, name: str, *, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f"{name} is outside its permitted range")
    return float(value)


def _text(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _mention_probabilities(inputs: dict, now: float) -> tuple[float, float, float]:
    cohort = _text(inputs["cohort"], "cohort")
    if inputs["comparability_reviewed"] is not True:
        raise ValueError("historical comparability must be explicitly reviewed")
    minimum = inputs["min_events"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 2:
        raise ValueError("min_events must be an integer of at least 2")
    events = inputs["events"]
    if not isinstance(events, list) or len(events) < minimum:
        raise ValueError("not enough comparable resolved events")
    ids, groups = set(), set()
    successes = 0
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("each historical event must be an object")
        event_id = _text(event["event_id"], "event_id")
        group = _text(event["group"], "group")
        if event_id in ids or group in groups:
            raise ValueError("historical event IDs and independent groups must be unique")
        ids.add(event_id)
        groups.add(group)
        if type(event["outcome_yes"]) is not bool:
            raise ValueError("historical outcome_yes must be true or false")
        resolved_at = _number(event["resolved_at"], "resolved_at", low=0)
        if resolved_at >= now:
            raise ValueError("historical events must resolve strictly before the decision")
        if event["cohort"] != cohort:
            raise ValueError("historical events must share the reviewed cohort")
        if event["resolution_source"] != inputs["resolution_source"]:
            raise ValueError("historical resolution sources must match the reviewed source")
        if event["yes_definition"] != inputs["target_yes_definition"]:
            raise ValueError("historical YES definitions must match the reviewed target definition")
        successes += event["outcome_yes"]
    lower, upper = wilson_interval(successes, len(events))
    return successes / len(events), lower, upper


def evaluate(strategy: dict, *, outcome: str, limit_price: float, fee_per_share: float,
             now: float, end_time: float, resolution_source: str, yes_definition: str,
             shares: float | None = None) -> dict:
    """Reject incomplete assumptions; compare the conservative outcome probability to cost.

    ``inputs`` schemas are documented in examples/strategy-inputs.md. NO uses one
    minus the upper YES bound. A manual decision deliberately supplies no forecast.
    """
    result = {"probability": None, "conservative_probability": None, "edge_per_share": None,
              "eligible": False, "reasons": [], "assumption": None}
    try:
        if not isinstance(strategy, dict):
            raise ValueError("strategy must be an object")
        kind = strategy["kind"]
        if kind not in ("model_value", "favorite_carry", "mention_base_rate", "manual", "indexed"):
            raise ValueError("unsupported strategy kind")
        inputs = strategy["inputs"]
        if not isinstance(inputs, dict):
            raise ValueError("strategy inputs must be an object")
        minimum_edge = _number(strategy["min_edge"], "min_edge", low=0)
        price = _number(limit_price, "limit_price", low=0, high=1)
        fee = _number(fee_per_share, "fee_per_share", low=0)
        if not 0 < price < 1 or price + fee >= 1:
            raise ValueError("entry cost must be strictly between zero and one dollar")
        now = _number(now, "now", low=0)
        end_time = _number(end_time, "end_time", low=0)
        if end_time <= now:
            raise ValueError("the contract must end after the decision")
        if outcome not in ("YES", "NO"):
            raise ValueError("outcome must be YES or NO")
        _text(resolution_source, "resolution_source")
        _text(yes_definition, "yes_definition")
        if kind == "indexed":
            from .strategy_catalog import trade_decision
            return trade_decision(strategy, outcome=outcome, limit_price=price, fee_per_share=fee,
                                  now=now, end_time=end_time, resolution_source=resolution_source,
                                  yes_definition=yes_definition, shares=shares)
        if kind == "manual":
            if minimum_edge != 0:
                raise ValueError("manual decisions have no edge estimate; min_edge must be zero")
            result.update(eligible=True, assumption="Reader's manual decision; no probability or edge estimated.")
            return result
        if inputs["target_yes_definition"] != yes_definition:
            raise ValueError("forecast YES definition does not match the approved contract")
        if inputs["resolution_source"] != resolution_source:
            raise ValueError("forecast resolution source does not match the approved contract")
        _text(inputs["evidence"], "evidence")
        _text(inputs["source_notes"], "source_notes")
        if kind == "mention_base_rate":
            probability, lower, upper = _mention_probabilities(inputs, now)
            result["assumption"] = ("Reader-reviewed comparable independent binary events; Wilson 95% bounds "
                                    "describe sample uncertainty, not future comparability or trading skill.")
        else:
            probability = _number(inputs["probability_yes"], "probability_yes", low=0, high=1)
            lower = _number(inputs["conservative_low_yes"], "conservative_low_yes", low=0, high=1)
            upper = _number(inputs["conservative_high_yes"], "conservative_high_yes", low=0, high=1)
            if not lower <= probability <= upper:
                raise ValueError("YES probability must lie within the conservative bounds")
            as_of = _number(inputs["as_of"], "as_of", low=0)
            valid_until = _number(inputs["valid_until"], "valid_until", low=0)
            if not as_of <= now < valid_until:
                raise ValueError("forecast must already exist and remain valid at the decision")
            result["assumption"] = "Reader-supplied independent forecast and bounds; their accuracy is unverified."
        outcome_probability = probability if outcome == "YES" else 1 - probability
        conservative = lower if outcome == "YES" else 1 - upper
        edge = conservative - price - fee
        result.update(probability=outcome_probability, conservative_probability=conservative, edge_per_share=edge)
        if edge < minimum_edge:
            result["reasons"].append("conservative edge after the entry fee is below min_edge")
        if kind == "favorite_carry":
            favorite_price = _number(inputs["min_favorite_price"], "min_favorite_price", low=0.5, high=1)
            if favorite_price == 1:
                raise ValueError("min_favorite_price must be less than one")
            minimum_return = _number(inputs["min_expected_annual_return"], "min_expected_annual_return", low=0)
            maximum_days = _number(inputs["max_days"], "max_days", low=0)
            if maximum_days == 0:
                raise ValueError("max_days must be positive")
            days = (end_time - now) / 86_400
            annual_return = edge / (price + fee) * 365 / days
            if not math.isfinite(annual_return):
                raise ValueError("expected annual return is not finite")
            if price < favorite_price:
                result["reasons"].append("entry price is below min_favorite_price")
            if days > maximum_days:
                result["reasons"].append("capital lock-up exceeds max_days")
            if annual_return < minimum_return:
                result["reasons"].append("conservative expected annual return is below the required minimum")
            result["assumption"] += (" Annual return is conservative expected net return on cost, scaled "
                                     "by 365/days without assumed compounding; actual settlement can be delayed.")
        result["eligible"] = not result["reasons"]
    except KeyError as error:
        result["reasons"].append(f"missing required field: {error.args[0]}")
    except (ValueError, TypeError, OverflowError) as error:
        result["reasons"].append(str(error))
    return result
