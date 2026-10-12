"""Indexed, reader-supplied evidence models; synthetic demos are never live forecasts.

Every result describes a decision under stated assumptions, not verified skill. A
returned forecast still needs the separate contract, quote and order checks.
shares, hedge_shares and planned_shares are shares bought (a BUY receives every
matched share), and fee_per_share is the cash fee per share paid on top of the
limit price. The trading bridge supplies the current fee and the order's size.
"""
from __future__ import annotations

import math

from .carry import holding_reward_hourly
from .crypto_pricing import call_spread_probability, norm_cdf, twap_up_probability
from .edge_check import brier, log_loss, wilson_interval
from .strategies import evaluate

INDICES = (7, 8, 10, 11, 12, 13, 14, 19, 20, 32, 33, 35)
# Strategy 13's market types: finishing above a level on the date, touching it at any moment before the date, or finishing between two levels.
PAYOFF_TYPES = ("finish_above", "touch", "range")


def _number(value, name, low=None, high=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f"{name} is outside its permitted range")
    return float(value)


def _integer(value, name, low=0):
    if type(value) is not int or value < low:
        raise ValueError(f"{name} must be an integer of at least {low}")
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value


def _json(value):
    """Reject nonfinite values even in unused or nested reader fields."""
    if type(value) in (int, float):
        _number(value, "JSON number")
    elif isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _json(child)
    elif isinstance(value, list):
        for child in value:
            _json(child)
    elif value is not None and type(value) not in (str, bool):
        raise ValueError("inputs must contain only JSON values")


def _common(inputs, now):
    if not isinstance(inputs, dict):
        raise ValueError("inputs must be an object")
    _json(inputs)
    now = _number(now, "now", 0)
    for field in ("target_yes_definition", "resolution_source", "evidence", "source_notes"):
        _text(inputs[field], field)
    contract = inputs["contract"]
    if not isinstance(contract, dict):
        raise ValueError("contract must be an object")
    if inputs["target_yes_definition"] != contract["yes_definition"]:
        raise ValueError("target YES definition does not match the reviewed contract")
    if inputs["resolution_source"] != contract["resolution_source"]:
        raise ValueError("resolution source does not match the reviewed contract")
    if not _number(inputs["as_of"], "as_of", 0) <= now < _number(inputs["valid_until"], "valid_until", 0):
        raise ValueError("dated evidence must already exist and remain valid")
    if _number(contract["end_time"], "end_time", 0) <= now:
        raise ValueError("contract must end after the decision")
    if inputs["outcome"] not in ("YES", "NO"):
        raise ValueError("outcome must be YES or NO")
    price = _number(inputs["limit_price"], "limit_price", 0, 1)
    fee = _number(inputs["fee_per_share"], "fee_per_share", 0)
    if not 0 < price < 1 or price + fee >= 1:
        raise ValueError("entry cost must be strictly between zero and one dollar")
    _number(inputs["min_edge"], "min_edge", 0)


def _forecast(inputs, probability, lower, upper):
    probability = _number(probability, "probability_yes", 0, 1)
    lower = _number(lower, "conservative_low_yes", 0, 1)
    upper = _number(upper, "conservative_high_yes", 0, 1)
    if not lower <= probability <= upper:
        raise ValueError("probability must be within the stated stress bounds")
    return {**{key: inputs[key] for key in ("as_of", "valid_until", "target_yes_definition",
                                          "resolution_source", "evidence", "source_notes")},
            "probability_yes": probability, "conservative_low_yes": lower,
            "conservative_high_yes": upper}


def _reader_forecast(inputs):
    return _forecast(inputs, inputs["probability_yes"], inputs["conservative_low_yes"],
                     inputs["conservative_high_yes"])


def _decision(inputs, forecast, now, kind="model_value", fee=None):
    return evaluate({"kind": kind, "min_edge": inputs["min_edge"], "inputs": forecast},
                    outcome=inputs["outcome"], limit_price=inputs["limit_price"],
                    fee_per_share=inputs["fee_per_share"] if fee is None else fee, now=now,
                    end_time=inputs["contract"]["end_time"],
                    resolution_source=inputs["contract"]["resolution_source"],
                    yes_definition=inputs["contract"]["yes_definition"])


def _bounded(inputs, probability):
    allowance = _number(inputs["uncertainty_allowance"], "uncertainty_allowance", 0, 1)
    if allowance == 0:
        raise ValueError("uncertainty_allowance must be positive")
    return _forecast(inputs, probability, max(0, probability - allowance), min(1, probability + allowance))


def _records(records, now):
    if not isinstance(records, list) or len(records) < 2 or not all(isinstance(row, dict) for row in records):
        raise ValueError("calibration_records needs at least two independent resolved decisions, each an object")
    ids, groups, probabilities, outcomes = set(), set(), [], []
    for row in records:
        identity, group = _text(row["event_id"], "event_id"), _text(row["group"], "group")
        if identity in ids or group in groups:
            raise ValueError("calibration IDs and independent groups must be unique")
        ids.add(identity)
        groups.add(group)
        if not _number(row["forecast_at"], "forecast_at", 0) < _number(row["resolved_at"], "resolved_at", 0) < now:
            raise ValueError("calibration forecasts must precede resolved outcomes and the decision")
        if type(row["outcome_yes"]) is not bool:
            raise ValueError("calibration outcomes must be true or false")
        probabilities.append(_number(row["probability_yes"], "calibration probability", 0, 1))
        outcomes.append(int(row["outcome_yes"]))
    return {"decisions": len(records), "brier_score": brier(probabilities, outcomes),
            "log_loss": log_loss(probabilities, outcomes)}


def _count_probability(observed, lower, upper, pace, days, variance):
    """Negative-binomial (gamma-Poisson) count of future posts: mean pace x days, variance
    multiplier x mean; Poisson at multiplier one. Sums the probabilities over the bucket."""
    mean = pace * days
    if upper is not None and upper < observed:
        return 0.0
    if mean == 0:
        return float(lower <= observed and (upper is None or observed <= upper))
    sd = math.sqrt(variance * mean)
    if mean > 100_000 or not 80 * sd + 40 * variance < 1_000_000:  # above 1e5 the log-gamma sums lose accuracy (3e-3 off at 1e6 with a multiplier near one)
        raise ValueError("count pace and variance are too large for the discrete count model")
    # Counts more than 40 standard deviations (or 40 multipliers) from the mean carry negligible probability.
    first = max(0, lower - observed, math.floor(mean - 40 * sd))
    last = math.ceil(mean + 40 * sd + 40 * variance)
    if upper is not None:
        last = min(last, upper - observed)
    if variance < 1 + 1e-6:  # indistinguishable from Poisson, and avoids lgamma cancellation at huge r
        log_pmf = lambda k: k * math.log(mean) - mean - math.lgamma(k + 1)  # noqa: E731
    else:
        r, q = mean / (variance - 1), 1 - 1 / variance
        log_pmf = lambda k: math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(1 - q) + k * math.log(q)  # noqa: E731
    return min(1.0, sum(math.exp(log_pmf(k)) for k in range(first, last + 1)))


def _normal_count_probability(observed, lower, upper, pace, days, variance):
    """Chapter 12's bell curve: continuity-corrected normal, conditioned on nonnegative new counts."""
    mean = pace * days
    if upper is not None and upper < observed:
        return 0.0
    if mean == 0:
        return float(lower <= observed and (upper is None or observed <= upper))
    sd = math.sqrt(variance * mean)
    support_cdf = norm_cdf((-0.5 - mean) / sd)
    low_cdf = norm_cdf((max(0, lower - observed) - 0.5 - mean) / sd)
    high_cdf = 1 if upper is None else norm_cdf((upper - observed + 0.5 - mean) / sd)
    return max(0.0, min(1.0, (high_cdf - low_cdf) / (1 - support_cdf)))


def analyze(index: int, inputs: dict, *, now: float) -> dict:
    """Analyze indexed strategy inputs; absence of ``forecast`` means analysis only.

    Common contract fields are the reviewed context, while top-level source and
    YES definition describe the reader's evidence. Equality is required. The
    trading toolkit replaces the contract context with its fresh inspection.
    """
    result = {"eligible": False, "reasons": [], "analysis": {"strategy_index": index if type(index) is int else None}}
    try:
        if type(index) is not int or index not in INDICES:
            raise ValueError("unsupported model strategy index")
        _common(inputs, now)
        detail = result["analysis"]
        forecast = None
        decision = None
        screen = None  # set when no pass/fail screen applies, so eligibility is null
        if index in (7, 10):
            forecast = _reader_forecast(inputs)
            kind = "favorite_carry" if index == 7 else "model_value"
            model_inputs = {**inputs, **forecast}
            decision = _decision(inputs, model_inputs, now, kind)
            detail["assumption"] = "Independent reader forecast; its accuracy and calibration remain unverified."
        elif index == 8:
            if inputs["reward_eligibility_verified"] is not True:
                raise ValueError("current holding-reward eligibility must be independently verified")
            _text(inputs["reward_terms_source"], "reward_terms_source")
            rate = _number(inputs["reward_rate_annual"], "reward_rate_annual", 0, 1)  # a fraction: 0.0325 is 3.25%
            midpoint = _number(inputs["midpoint"], "midpoint", 0, 1)
            shares = _number(inputs["shares"], "shares", 0)
            days = _number(inputs["holding_days"], "holding_days", 0)
            scheduled_days = (inputs["contract"]["end_time"] - now) / 86400
            if shares == 0 or days == 0 or days * 86400 + 1 < scheduled_days * 86400:
                raise ValueError("positive shares and holding_days must cover the scheduled settlement horizon")
            probability = _number(inputs["probability_yes"], "probability_yes", 0, 1)
            probability = probability if inputs["outcome"] == "YES" else 1 - probability
            rewards = holding_reward_hourly(shares, midpoint, 0, 0, rate) * 24 * min(days, scheduled_days)
            cost = shares * (inputs["limit_price"] + inputs["fee_per_share"])
            alternative = cost * _number(inputs["alternative_rate_annual"], "alternative_rate_annual", 0, 1) * days / 365
            received = _number(inputs["actual_rewards_received"], "actual_rewards_received", 0)
            net = shares * probability - cost + rewards - alternative
            detail.update(estimated_rewards=rewards, actual_rewards_received=received,
                          estimated_net_after_alternative=net, entry_cost=cost, scheduled_holding_days=scheduled_days,
                          assumption="Reward estimate assumes holding to scheduled settlement with unchanged midpoint, rate and eligibility; "
                                     "no rewards after that date are projected, while alternative-interest cost covers the full supplied "
                                     "holding budget. Settlement delays can exceed that budget and receipts are separate. "
                                     "Analysis only: reward eligibility and future receipts are not enforced by the order toolkit.")
            if net <= 0:
                result["reasons"].append("estimated net return after costs and the alternative is not positive")
        elif index == 11:
            if inputs["measurement_reviewed"] is not True:
                raise ValueError("station, units, local date and settlement measurement must be reviewed")
            _text(inputs["station_id"], "station_id")
            members = inputs["members"]
            if not isinstance(members, list) or len(members) < 2:
                raise ValueError("members must contain at least two ensemble measurements")
            members = [_number(value, "ensemble member") for value in members]
            lower = _number(inputs["bucket_lower"], "bucket_lower")
            upper = _number(inputs["bucket_upper"], "bucket_upper")
            if lower >= upper:
                raise ValueError("bucket_lower must be below bucket_upper")
            # Half-open [lower, upper): a member on a shared edge counts in exactly one bucket.
            raw = sum(lower <= member < upper for member in members) / len(members)
            bias = _number(inputs["probability_bias_adjustment"], "probability_bias_adjustment", -1, 1)
            probability = max(0, min(1, raw + bias))
            forecast = _bounded(inputs, probability)
            detail.update(raw_member_frequency=raw, member_count=len(members),
                          assumption="Correlated ensemble members are not independent resolved trials. Reader bias and stress "
                                     "allowance are assumptions; these bounds are not a Wilson confidence interval.")
        elif index == 12:
            if inputs["human_reviewed"] is not True:
                raise ValueError("LLM source provenance and contract reasoning require explicit human review")
            _text(inputs["calibration_notes"], "calibration_notes")
            forecasts = inputs["forecasts"]
            if not isinstance(forecasts, list) or not forecasts or not all(isinstance(row, dict) for row in forecasts):
                raise ValueError("forecasts must be a nonempty list of objects")
            weighted, weights, names = 0.0, 0.0, set()
            for row in forecasts:
                name = _text(row["model"], "model")
                if name in names:
                    raise ValueError("model IDs must be unique")
                names.add(name)
                _text(row["source"], "source")
                weight = _number(row["weight"], "weight", 0)
                weighted += weight * _number(row["probability_yes"], "LLM probability", 0, 1)
                weights += weight
            if not weights > 0 or not math.isfinite(weights + weighted):
                raise ValueError("forecast weights must have a finite positive sum")
            forecast = _bounded(inputs, weighted / weights)
            detail.update(forecast_count=len(forecasts),
                          assumption="Reader-reviewed sourced model outputs; correlated models and fabricated citations can invalidate "
                                     "the estimate. Stress bounds are reader allowances, not measured confidence.")
        elif index == 13:
            if inputs["option_contract_match_reviewed"] is not True:
                raise ValueError("option expiry, underlying, settlement, currency, payoff type, observation window and contract definition must be reviewed")
            if inputs["risk_neutral_to_real_reviewed"] is not True:
                raise ValueError("risk-neutral option pricing must be reviewed before interpreting an actual probability")
            _text(inputs["conversion_notes"], "conversion_notes")
            payoff = inputs["payoff_type"]
            if payoff not in PAYOFF_TYPES:
                raise ValueError("payoff_type must be finish_above, touch or range")
            reference = call_spread_probability(_number(inputs["call_low_cost"], "call_low_cost", 0),
                                               _number(inputs["call_high_cost"], "call_high_cost", 0),
                                               _number(inputs["strike_width"], "strike_width", 0))
            if payoff == "finish_above":
                payoff_reference = reference
            elif payoff == "range":
                # Finishing between two levels: the chance of finishing above the lower one minus that of finishing above the upper one.
                upper = call_spread_probability(_number(inputs["upper_call_low_cost"], "upper_call_low_cost", 0),
                                                _number(inputs["upper_call_high_cost"], "upper_call_high_cost", 0),
                                                _number(inputs["upper_strike_width"], "upper_strike_width", 0))
                if upper > reference:
                    raise ValueError("the upper call spread's finish-above reference exceeds the lower one's; check the range's strikes")
                payoff_reference = reference - upper
                detail["upper_option_implied_reference"] = upper
            else:
                # A call spread prices finishing above a level, not touching it at any moment: a touch market needs the reader's own conversion.
                if inputs.get("touch_probability") is None:
                    raise ValueError("a touch market needs touch_probability: the option reference is a finish-above (terminal) chance, "
                                     "so convert it first (for example with crypto_pricing.touch_probability) or do not use this tool")
                payoff_reference = _number(inputs["touch_probability"], "touch_probability", 0, 1)
                _text(inputs["touch_conversion_notes"], "touch_conversion_notes")
            adjusted = payoff_reference + _number(inputs["probability_adjustment"], "probability_adjustment", -1, 1)
            if not 0 <= adjusted <= 1:
                raise ValueError("option-implied reference plus probability_adjustment must lie between 0 and 1")
            forecast = _forecast(inputs, adjusted, inputs["conservative_low_yes"], inputs["conservative_high_yes"])
            detail.update(option_implied_reference=reference, payoff_type=payoff, payoff_reference=payoff_reference,
                          assumption="In a zero-interest dollar model, call-spread cost divided by strike width averages risk-neutral terminal (finish-above) "
                                     "probabilities over that strike interval; a range subtracts a second spread's reference, and a touch market uses the "
                                     "reader's own touch_probability instead. Actual YES probability requires the reader's adjustment and stress bounds; "
                                     "those bounds are not statistical confidence intervals or an exact digital replication.")
        elif index == 14:
            if inputs["settlement_window_reviewed"] is not True:
                raise ValueError("settlement source, averaging ticks, window and tie rule must be reviewed")
            n = _integer(inputs["seconds_left"], "seconds_left")
            window = _integer(inputs["window_seconds"], "window_seconds", 1)
            known = inputs["observed_prices"]
            if not isinstance(known, list) or len(known) != window - n:
                raise ValueError("observed_prices must contain exactly window minus seconds_left prices")
            known = [_number(value, "observed price", 0) for value in known]
            probability = twap_up_probability(sum(known), _number(inputs["last_price"], "last_price", 0), n,
                                              _number(inputs["sigma_per_second"], "sigma_per_second", 0),
                                              _number(inputs["price_to_beat"], "price_to_beat", 0), window)
            edge = (probability if inputs["outcome"] == "YES" else 1 - probability) - inputs["limit_price"] - inputs["fee_per_share"]
            detail.update(model_probability_up=probability, seconds_left=n, edge_per_share=edge,
                          assumption="Driftless normal one-second price walk, exact averaging source and Up-on-tie rule; YES is Up. "
                                     "The screen compares the model's point probability (no stress bounds) with price plus fee. "
                                     "Analysis only: the order toolkit's minimum GTD lifetime cannot support a late-window signal.")
            if edge < inputs["min_edge"]:
                result["reasons"].append("model probability after the entry fee is below min_edge")
        elif index == 19:
            if not isinstance(inputs["events"], list) or not all(isinstance(row, dict) for row in inputs["events"]):
                raise ValueError("events must be a list of objects")
            if any(_number(row["resolved_at"], "resolved_at", 0) > inputs["as_of"] for row in inputs["events"]):
                raise ValueError("historical outcomes must already exist at the evidence as_of time")
            decision = _decision(inputs, inputs, now, "mention_base_rate")
            if decision["probability"] is not None:
                successes = sum(row["outcome_yes"] for row in inputs["events"])
                lower, upper = wilson_interval(successes, len(inputs["events"]))
                forecast = _forecast(inputs, successes / len(inputs["events"]), lower, upper)
                detail.update(events=len(inputs["events"]), successes=successes,
                              assumption=decision["assumption"])
        elif index == 20:
            if inputs["settlement_counter_reviewed"] is not True:
                raise ValueError("counting source, included posts, timezone and window require review")
            _text(inputs["model_notes"], "model_notes")
            observed = _integer(inputs["observed_count"], "observed_count")
            lower = _integer(inputs["count_lower"], "count_lower")
            upper = inputs["count_upper"]
            if upper is not None and _integer(upper, "count_upper") < lower:
                raise ValueError("count_upper must not be below count_lower")
            days = _number(inputs["days_remaining"], "days_remaining", 0)
            if days == 0 or days * 86400 > inputs["contract"]["end_time"] - now:
                raise ValueError("remaining count window must be positive and fit the contract horizon")
            pace = _number(inputs["pace_per_day"], "pace_per_day", 0)
            variance = _number(inputs["variance_multiplier"], "variance_multiplier", 1)
            paces, variances = inputs["stress_paces"], inputs["stress_variances"]
            if not isinstance(paces, list) or not paces or not isinstance(variances, list) or not variances:
                raise ValueError("stress_paces and stress_variances must be nonempty lists")
            # the main pace and multiplier are always stressed too; a value listed twice is one scenario
            paces = list(dict.fromkeys([_number(value, "stress pace", 0) for value in paces] + [pace]))
            variances = list(dict.fromkeys([_number(value, "stress variance", 1) for value in variances] + [variance]))
            probability = _count_probability(observed, lower, upper, pace, days, variance)
            scenarios = [_count_probability(observed, lower, upper, p, days, v) for p in paces for v in variances]
            allowance = _number(inputs["uncertainty_allowance"], "uncertainty_allowance", 0, 1)
            if allowance == 0:
                raise ValueError("uncertainty_allowance must be positive")
            forecast = _forecast(inputs, probability, max(0, min(scenarios) - allowance), min(1, max(scenarios) + allowance))
            detail.update(expected_final_count=observed + pace * days,
                          future_count_standard_deviation=math.sqrt(variance * pace * days),
                          normal_approximation_probability=_normal_count_probability(observed, lower, upper, pace, days, variance),
                          stress_scenarios=len(scenarios),
                          assumption="Future posts follow a negative-binomial count with mean pace x days and variance "
                                     "variance_multiplier x mean (Poisson at 1); burstiness is an input. "
                                     "normal_approximation_probability is the continuity-corrected bell curve of Chapter 12's toy, "
                                     "for comparison only: it is unreliable when few posts remain. Bounds cover only supplied discrete "
                                     "stress scenarios plus allowance, not all possible parameters, prediction error or measured confidence.")
        elif index == 32:
            _text(inputs["domain"], "domain")
            _text(inputs["method"], "method")
            if inputs["calibration_reviewed"] is not True:
                raise ValueError("expertise requires an explicit review of the prior forecasting record")
            record = _records(inputs["calibration_records"], now)
            if any(row["resolved_at"] > inputs["as_of"] for row in inputs["calibration_records"]):
                raise ValueError("calibration outcomes must already exist at the evidence as_of time")
            minimum = _integer(inputs["min_decisions"], "min_decisions", 2)
            detail.update(record, min_decisions=minimum, brier_score_always_50_percent=0.25,
                          assumption="Prior record scores describe observed forecasts, not established expertise or future trading profit.")
            if record["decisions"] < minimum:
                result["reasons"].append("calibration record has fewer resolved decisions than min_decisions")
            if record["brier_score"] >= 0.25:
                result["reasons"].append("calibration record's Brier score is no better than always forecasting 50% (0.25)")
            forecast = _reader_forecast(inputs)
        elif index == 33:
            n = _integer(inputs["sample_size"], "sample_size", 2)
            a, b = _number(inputs["share_a"], "share_a", 0, 1), _number(inputs["share_b"], "share_b", 0, 1)
            if a + b > 1:
                raise ValueError("mutually exclusive polling shares must add to at most one")
            design = _number(inputs["design_effect"], "design_effect", 1)
            se = math.sqrt(design * (a + b - (a - b) ** 2) / n)
            lead = a - b
            detail.update(vote_share_lead=lead, lead_standard_error=se,
                          lead_sampling_interval=[max(-1, lead - 1.96 * se), min(1, lead + 1.96 * se)],
                          assumption="Multinomial sampling error adjusted by design effect; it excludes turnout, nonresponse and "
                                     "systematic polling errors. A vote share or lead is not an election-win probability.")
            if inputs.get("election_model_reviewed") is True:
                _text(inputs["calibration_notes"], "calibration_notes")
                forecast = _reader_forecast(inputs)
                poll_cost = _number(inputs["poll_cost"], "poll_cost", 0)
                shares = _number(inputs["planned_shares"], "planned_shares", 0)
                if shares == 0:
                    raise ValueError("planned_shares must be positive to allocate polling cost")
                allocated = poll_cost / shares
                detail["allocated_poll_cost_per_share"] = allocated
                decision = _decision(inputs, forecast, now, fee=inputs["fee_per_share"] + allocated)
            else:
                detail["requires_calibrated_forecast"] = True
                screen = ("none: a poll's lead and its sampling interval are descriptive; a decision needs "
                          "election_model_reviewed and a calibrated election forecast, so eligible is null")
        elif index == 35:
            _text(inputs["exposure_description"], "exposure_description")
            shares = _number(inputs["hedge_shares"], "hedge_shares", 0)
            if shares == 0:
                raise ValueError("hedge_shares must be positive")
            premium = shares * (inputs["limit_price"] + inputs["fee_per_share"])
            maximum = _number(inputs["max_hedge_cost"], "max_hedge_cost", 0)
            minimum = _number(inputs["min_worst_loss_reduction"], "min_worst_loss_reduction", 0)
            scenarios = inputs["scenarios"]
            if not isinstance(scenarios, list) or len(scenarios) < 2 or not all(isinstance(row, dict) for row in scenarios):
                raise ValueError("hedge requires at least two distinct exposure scenarios, each an object")
            rows, ids, outcomes = [], set(), set()
            for row in scenarios:
                identity = _text(row["scenario_id"], "scenario_id")
                if identity in ids or type(row["contract_yes"]) is not bool:
                    raise ValueError("hedge scenario IDs must be unique and contract_yes binary")
                ids.add(identity)
                outcomes.add(row["contract_yes"])
                loss = _number(row["real_world_loss"], "real_world_loss", 0)
                payout = shares if row["contract_yes"] == (inputs["outcome"] == "YES") else 0
                rows.append({"scenario_id": identity, "loss_before": loss,
                             "contract_payout": payout, "loss_after": loss + premium - payout})
            if outcomes != {True, False}:
                raise ValueError("hedge scenarios must include both contract outcomes and uncovered basis risk")
            before, after = max(row["loss_before"] for row in rows), max(row["loss_after"] for row in rows)
            detail.update(scenarios=rows, premium=premium, worst_loss_before=before, worst_loss_after=after,
                          worst_loss_reduction=before - after,
                          largest_uncovered_loss=max(row["loss_before"] for row in rows if not row["contract_payout"]),
                          assumption="Analysis only: loss reduction covers supplied scenarios, including reader-entered basis risk. "
                                     "No event probability, expected profit or guaranteed comprehensive hedge is inferred.")
            if premium > maximum:
                result["reasons"].append("hedge premium exceeds max_hedge_cost")
            if before - after <= 0 or before - after < minimum:
                result["reasons"].append("hedge does not sufficiently reduce the supplied worst-case loss")
        if forecast is not None:
            result["forecast"] = forecast
            if decision is None:
                decision = _decision(inputs, forecast, now)
        if decision is not None:
            detail["decision"] = decision
            result["reasons"].extend(decision["reasons"])
        _json(result)
        if screen:
            result.update(eligible=None, decision_screen=screen)
        else:
            result["eligible"] = not result["reasons"]
    except KeyError as error:
        result["reasons"].append(f"missing required field: {error.args[0]}")
    except (ValueError, OverflowError, ZeroDivisionError) as error:  # a TypeError is a code fault and propagates
        result["reasons"].append(str(error))
    try:
        _json(result)
    except (ValueError, TypeError, OverflowError):
        return {"eligible": False, "reasons": ["calculation exceeds the finite numeric range"],
                "analysis": {"strategy_index": index if type(index) is int else None}}
    return result


def demo_inputs(index: int, now: float) -> dict:
    """Complete, explicitly synthetic JSON schemas for all supported indexed methods."""
    if type(index) is not int or index not in INDICES:
        raise ValueError("unsupported model strategy index")
    now = _number(now, "now", 1_000_000)
    definition = "Synthetic demo metric meets its explicitly reviewed condition."
    source = "https://example.invalid/synthetic-official-source"
    inputs = {"target_yes_definition": definition, "resolution_source": source,
              "evidence": "SYNTHETIC DEMONSTRATION ONLY; replace with dated independent evidence before considering a trade.",
              "source_notes": "Made-up input schema; no observed forecasting skill, market opportunity or trading performance.",
              "as_of": now - 60, "valid_until": now + 3600,
              "contract": {"yes_definition": definition, "resolution_source": source, "end_time": now + 30 * 86400},
              "outcome": "YES", "limit_price": 0.35, "fee_per_share": 0.01, "min_edge": 0.02}
    if index in (7, 10, 32):
        inputs.update(probability_yes=0.75, conservative_low_yes=0.65, conservative_high_yes=0.85)
    if index == 7:
        inputs.update(limit_price=0.95, probability_yes=0.995, conservative_low_yes=0.98,
                      conservative_high_yes=1, min_edge=0.01, min_favorite_price=0.9,
                      min_expected_annual_return=0.05, max_days=90)
    elif index == 8:
        inputs.update(reward_eligibility_verified=True, reward_terms_source=source,
                      reward_rate_annual=0.0325, midpoint=0.96, shares=100, holding_days=30,
                      probability_yes=0.99, limit_price=0.95, alternative_rate_annual=0.04,
                      actual_rewards_received=0)
    elif index == 11:
        inputs.update(measurement_reviewed=True, station_id="SYNTHETIC-STATION", bucket_lower=19.5,
                      bucket_upper=22.5, members=[20, 20.5, 21, 21.5, 22, 21, 21, 22, 23, 24],
                      probability_bias_adjustment=-0.05, uncertainty_allowance=0.15)
    elif index == 12:
        inputs.update(human_reviewed=True, calibration_notes="Synthetic schema: replace with held-out calibration and correlation review.",
                      forecasts=[{"model": "synthetic-model-A", "probability_yes": 0.75, "weight": 1, "source": source},
                                 {"model": "synthetic-model-B", "probability_yes": 0.7, "weight": 1, "source": source}],
                      uncertainty_allowance=0.15)
    elif index == 13:
        inputs.update(option_contract_match_reviewed=True, risk_neutral_to_real_reviewed=True, payoff_type="finish_above",
                      conversion_notes="Synthetic USD terminal call spread; assumed actual probability adjustment is zero for this arithmetic demo.",
                      call_low_cost=100, call_high_cost=30, strike_width=100, probability_adjustment=0,
                      conservative_low_yes=0.5, conservative_high_yes=0.9)
    elif index == 14:
        inputs.update(settlement_window_reviewed=True, window_seconds=60, seconds_left=20,
                      observed_prices=[100.01] * 39 + [100.02], last_price=100.02, sigma_per_second=0.01, price_to_beat=100)
    elif index == 19:
        inputs.update(cohort="synthetic-independent-speeches", comparability_reviewed=True, min_events=20,
                      events=[{"event_id": f"synthetic-speech-{i}", "group": f"synthetic-independent-event-{i}",
                               "outcome_yes": i < 18, "resolved_at": now - (i + 1) * 3600,
                               "cohort": "synthetic-independent-speeches", "resolution_source": source,
                               "yes_definition": definition} for i in range(20)])
    elif index == 20:
        inputs.update(settlement_counter_reviewed=True, model_notes="Synthetic overdispersed pace model, not a fitted predictive model.",
                      observed_count=58, count_lower=180, count_upper=219, days_remaining=5, pace_per_day=29,
                      # 6 is Chapter 12's illustration; the book's weekly count data imply about 16 to 22, so the stress covers 6, 16 and 24
                      variance_multiplier=6, stress_paces=[25, 33], stress_variances=[6, 16, 24],
                      uncertainty_allowance=0.05, limit_price=0.1)
    elif index == 32:
        inputs.update(domain="Synthetic specialty", method="Document primary sources before estimating probability.",
                      calibration_reviewed=True, min_decisions=20,
                      calibration_records=[{"event_id": f"synthetic-prior-{i}", "group": f"synthetic-group-{i}",
                                            "probability_yes": p, "outcome_yes": y,
                                            "forecast_at": now - 3 * 86400, "resolved_at": now - 86400}
                                           for i, (p, y) in enumerate([(0.7, True), (0.4, False)] * 10)])
    elif index == 33:
        inputs.update(sample_size=800, share_a=0.52, share_b=0.48, design_effect=1.5,
                      election_model_reviewed=True, calibration_notes="Synthetic separate election forecast, not inferred from the poll's lead.",
                      probability_yes=0.75, conservative_low_yes=0.6, conservative_high_yes=0.85,
                      poll_cost=10, planned_shares=100)
    elif index == 35:
        inputs.update(exposure_description="Synthetic cost increase; includes an uncovered moderate rise.",
                      hedge_shares=500, max_hedge_cost=200, min_worst_loss_reduction=200,
                      scenarios=[{"scenario_id": "no-increase", "real_world_loss": 0, "contract_yes": False},
                                 {"scenario_id": "moderate-uncovered-rise", "real_world_loss": 200, "contract_yes": False},
                                 {"scenario_id": "large-covered-rise", "real_world_loss": 1000, "contract_yes": True}])
    return inputs
