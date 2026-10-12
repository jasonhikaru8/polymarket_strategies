"""The book's exact strategy order and the bridge from analysis to reviewed orders."""
from __future__ import annotations

import importlib
import json
import math
import re
import time

# index, original card ID, chapter, filename stem, descriptive name, execution mode
STRATEGIES = (
    (1, "A1", 6, "binary_parity", "Binary parity arbitrage", "analysis"),
    (2, "A2", 6, "negrisk_bundles", "Multi-outcome bundle arbitrage", "analysis"),
    (3, "A3", 7, "logical_arbitrage", "Logical and combinatorial arbitrage", "analysis"),
    (4, "A4", 7, "date_ladder", "Date-ladder spreads", "analysis"),
    (5, "A5", 7, "cross_venue", "Cross-venue arbitrage", "analysis"),
    (6, "A6", 7, "legged_accumulation", "Legged complete-set accumulation", "analysis"),
    (7, "C8", 8, "favorite_carry", "Buying favorites", "forecast_order"),
    (8, "C9", 8, "holding_rewards", "Holding-reward carry", "analysis"),
    (9, "C4", 8, "tail_ladder", "Tail-bucket laddering", "analysis"),
    (10, "C1", 9, "model_value", "Model-based value betting", "forecast_order"),
    (11, "C3", 9, "weather_ensemble", "Weather ensemble bucket trading", "forecast_order"),
    (12, "C2", 9, "llm_forecasts", "AI forecasting and agent traders", "forecast_order"),
    (13, "C5", 10, "options_value", "Options-implied fair value", "forecast_order"),
    (14, "C6", 10, "twap_pricing", "Pricing short crypto markets with averages", "analysis"),
    (15, "B1", 11, "news_catalysts", "News and catalyst trading", "forecast_order"),
    (16, "B2", 11, "overreaction_fade", "Overreaction fade", "forecast_order"),
    (17, "B3", 11, "macro_calendar", "Macro-calendar trading", "forecast_order"),
    (18, "B4", 11, "attention_rotation", "Attention rotation", "forecast_order"),
    (19, "B5", 12, "mention_markets", "Mention markets", "forecast_order"),
    (20, "B6", 12, "count_buckets", "Bucketed count markets", "forecast_order"),
    (21, "C10", 12, "launch_fdv", "Crypto launch and FDV markets", "analysis"),
    (22, "D1", 13, "crypto_latency", "Latency trading on short crypto markets", "analysis"),
    (23, "D2", 13, "sports_latency", "Live sports and esports data latency", "analysis"),
    (24, "D3", 13, "oscillation_scalping", "Oscillation scalping", "analysis"),
    (25, "B7", 14, "resolution_rules", "Rules and resolution-source edge", "forecast_order"),
    (26, "B8", 14, "dispute_windows", "Dispute-window and resolution-lag trading", "analysis"),
    (27, "E1", 15, "inventory_quotes", "Market making with inventory", "analysis"),
    (28, "E2", 15, "liquidity_rewards", "Liquidity rewards", "analysis"),
    (29, "E3", 15, "sportsbook_quotes", "Sportsbook-anchored quoting", "analysis"),
    (30, "F1", 16, "whale_copying", "Whale tracking and copy trading", "analysis"),
    (31, "F2", 16, "wallet_flow", "Fresh-wallet and insider-flow monitoring", "analysis"),
    (32, "G1", 17, "domain_expertise", "Domain expertise and primary data", "forecast_order"),
    (33, "G2", 17, "polling", "Commissioned polling", "forecast_order"),
    (34, "G3", 17, "public_information", "Early information from public sources", "forecast_order"),
    (35, "H2", 17, "exposure_hedge", "Hedging real-world exposures", "analysis"),
)
BASKETS = {1, 2, 3, 4, 5, 6, 9, 21}
MODELS = {7, 8, 10, 11, 12, 13, 14, 19, 20, 32, 33, 35}
# Key names (lower-cased, punctuation removed) that mean a credential, however they are spelled: privateKey, api-secret, seed_phrase...
SECRET_WORDS = ("privatekey", "apikey", "apisecret", "secret", "passphrase", "password", "credential", "mnemonic", "seedphrase", "recoveryphrase",
                "signerkey", "walletkey", "sshkey", "keystore", "bearer", "authorization")
MAX_DEPTH = 60  # inputs nested deeper than this are refused: no real input needs it, and Python's own recursion limit is not a clean error
# Placeholder text the synthetic examples carry: inputs that still contain it were never replaced with real evidence.
PLACEHOLDER_MARKERS = ("example.invalid", "SYNTHETIC")


def get(index: int) -> dict:
    if type(index) is not int or not 1 <= index <= 35:
        raise ValueError("Strategy index must be an integer from 1 to 35")
    number, card, chapter, stem, name, mode = STRATEGIES[index - 1]
    return {"index": number, "id": card, "chapter": chapter, "name": name, "execution_mode": mode,
            "path": f"chapters/ch{chapter:02d}/strategy_{number:02d}_{card}_{stem}.py"}


def finite(value) -> bool:
    """True for a finite number; an integer too large for a float counts as not finite instead of raising OverflowError."""
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_inputs(value, depth: int = 0) -> None:
    """Reject credentials, nonfinite numbers and absurd nesting before saving or analyzing reader JSON."""
    if depth > MAX_DEPTH:
        raise ValueError("Strategy inputs are nested too deeply")
    if isinstance(value, dict):
        for key, item in value.items():
            plain = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(word in plain for word in SECRET_WORDS):
                raise ValueError("Credentials belong in the local environment, never strategy inputs")
            validate_inputs(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            validate_inputs(item, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Strategy inputs must contain only finite numbers")


PLACEHOLDER_MESSAGE = ("The inputs still contain placeholder text from the synthetic example (example.invalid or SYNTHETIC); "
                       "replace it with your own sources and evidence")


def contains_placeholders(value, depth: int = 0) -> bool:
    """True if any text value still holds the made-up example's placeholder text."""
    if depth > MAX_DEPTH:
        raise ValueError("Strategy inputs are nested too deeply")
    if isinstance(value, dict):
        return any(contains_placeholders(item, depth + 1) for item in value.values())
    if isinstance(value, list):
        return any(contains_placeholders(item, depth + 1) for item in value)
    return isinstance(value, str) and any(marker in value for marker in PLACEHOLDER_MARKERS)


def reject_placeholders(value) -> None:
    """Refuse inputs that still hold the made-up example's placeholder text (the `demo` flag alone is easy to delete)."""
    if contains_placeholders(value):
        raise ValueError(PLACEHOLDER_MESSAGE)


def own_min_edge(parameters: dict) -> float:
    """The minimum edge the reader wrote in the inputs file (0 when absent)."""
    value = parameters.get("min_edge", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not finite(value) or value < 0:
        raise ValueError("min_edge in the inputs must be a finite, nonnegative number")
    return float(value)


def _module(index: int):
    get(index)
    family = "baskets" if index in BASKETS else "models" if index in MODELS else "signals"
    return importlib.import_module(f".strategy_{family}", __package__)


def example(index: int, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    # The marker prevents an untouched synthetic example from becoming an order plan.
    return {**_module(index).demo_inputs(index, now), "demo": True}


def analyze(index: int, inputs: dict, *, now: float | None = None) -> dict:
    metadata = get(index)
    now = time.time() if now is None else now
    try:
        if not isinstance(inputs, dict):
            raise ValueError("Strategy inputs must be a JSON object")
        validate_inputs(inputs)
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now) or now < 0:
            raise ValueError("Decision time must be finite and nonnegative")
        result = _module(index).analyze(index, inputs, now=now)
        json.dumps(result, allow_nan=False)  # do not publish an infinite calculated edge
    except (ValueError, KeyError, OverflowError, RecursionError) as error:
        result = {"eligible": False, "reasons": [str(error)], "analysis": {}}
    demo = isinstance(inputs, dict) and inputs.get("demo") is True
    try:
        placeholder = isinstance(inputs, dict) and contains_placeholders(inputs)
    except (ValueError, RecursionError):
        placeholder = False  # too deeply nested: already refused above
    if placeholder and not demo:
        # The demo marker was removed but the made-up text was not: as `strategy prepare` does, refuse to call this eligible.
        result = {**result, "eligible": False, "reasons": [PLACEHOLDER_MESSAGE, *result["reasons"]]}
    return {**result, "strategy": metadata, "order_authorized": False, "synthetic": demo or placeholder}


def trade_decision(strategy: dict, *, outcome: str, limit_price: float, fee_per_share: float,
                   now: float, end_time: float, resolution_source: str, yes_definition: str,
                   shares: float | None = None) -> dict:
    """Recompute an indexed method against the *current* approved contract and quote.

    Analysis-only methods cannot be relabeled as executable. Eligible forecast methods
    still pass the existing conservative held-to-resolution value check.
    """
    from .strategies import evaluate

    result = {"probability": None, "conservative_probability": None, "edge_per_share": None,
              "eligible": False, "reasons": [], "assumption": None}
    try:
        index, parameters = strategy["inputs"]["strategy_index"], strategy["inputs"]["parameters"]
        meta = get(index)
        if meta["execution_mode"] != "forecast_order":
            raise ValueError("This indexed strategy supplies analysis/proposals only; it cannot submit orders")
        if not isinstance(parameters, dict) or parameters.get("demo") is True:
            raise ValueError("Complete real documented inputs; synthetic examples cannot support orders")
        reject_placeholders(parameters)
        minimum = max(strategy["min_edge"], own_min_edge(parameters))  # the stricter of the plan's and the inputs' minimum
        effective = {**parameters, "outcome": outcome, "limit_price": limit_price,
                     "fee_per_share": fee_per_share, "min_edge": minimum,
                     "contract": {"yes_definition": yes_definition, "resolution_source": resolution_source,
                                  "end_time": end_time}}
        if index == 33:
            if isinstance(shares, bool) or not isinstance(shares, (int, float)) or not math.isfinite(shares) or shares <= 0:
                raise ValueError("The actual order quantity is required to allocate polling cost")
            # Every matched share is delivered, so the poll cost is spread over the order size.
            effective["planned_shares"] = shares
        report = analyze(index, effective, now=now)
        result.update(strategy=meta, analysis=report["analysis"])
        if report["eligible"] is not True:
            screen = report["analysis"].get("decision_screen") if isinstance(report.get("analysis"), dict) else None
            result["reasons"] = report["reasons"] or [screen or "The indexed method did not pass its decision checks"]
            return result
        forecast = report.get("forecast")
        if not isinstance(forecast, dict):
            raise ValueError("This method has no reviewed held-to-resolution forecast for an order")
        decision = evaluate({"kind": "model_value", "min_edge": minimum, "inputs": forecast},
                            outcome=outcome, limit_price=limit_price, fee_per_share=fee_per_share, now=now,
                            end_time=end_time, resolution_source=resolution_source, yes_definition=yes_definition)
        if index == 33:
            entry_edge = decision["edge_per_share"]
            decision = {**decision, **report["analysis"]["decision"], "entry_only_edge_per_share": entry_edge}
        return {**result, **decision, "forecast_valid_until": forecast["valid_until"],
                "assumption": f"Strategy {index} ({meta['id']}): {report['analysis'].get('assumption') or decision['assumption']}"}
    except (ValueError, KeyError, OverflowError, RecursionError) as error:
        result["reasons"].append(str(error))
    return result
