"""Public contract inspection and bounded single-outcome trade previews. No credentials."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict
from datetime import timezone
from decimal import Decimal, InvalidOperation

from polymarket import AsyncPublicClient

from .data import yes_no_tokens
from .fees import fee_per_share, schedule_from_market


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def decimal(value, name: str, *, positive: bool = True) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return result


def timestamp(value, name: str) -> float:
    return float(decimal(value, name))


def contract_of(market) -> dict:
    """Fingerprint the exact public question, rules, source, deadline and outcome mapping."""
    yes, no = market.outcomes.yes, market.outcomes.no
    assets = yes_no_tokens(market)
    if yes is None or no is None or assets is None:
        raise ValueError("Only binary YES/NO markets with a known protocol version (v1 or v2) and two different outcome IDs of that version are supported")
    if not market.condition_id or not market.description or not market.question or market.state.end_date is None:
        raise ValueError("Contract identity, full rules or deadline unavailable")
    # YES and NO are positions in the outcome list: only a market whose outcomes really are "Yes" and "No" fits the toolkit's wording.
    if (str(yes.label).strip().lower(), str(no.label).strip().lower()) != ("yes", "no"):
        raise ValueError("Only markets whose two outcomes are labeled Yes and No are supported; team, Up/Down and Over/Under markets are not")
    end = market.state.end_date
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)  # a date without a zone is read as UTC, not as this computer's time
    return {
        "slug": market.slug, "condition_id": str(market.condition_id),
        "question": market.question, "description": market.description,
        "resolution_source": market.resolution.source,
        "end_time": end.timestamp(), "version": str(market.version) if market.version else None,
        "neg_risk": market.state.neg_risk,
        "tokens": {"YES": assets[0], "NO": assets[1]},  # asset IDs: V1 token IDs or V2 position IDs, chosen by `version`
        "labels": {"YES": yes.label, "NO": no.label},
    }


async def inspect(slug: str, client=None) -> dict:
    if client is None:
        async with AsyncPublicClient() as public:
            return await inspect(slug, public)
    markets = (await client.list_markets(slug=[slug], closed=False, page_size=2).first_page()).items
    matches = [m for m in markets if m.slug == slug]
    if len(matches) != 1:
        raise ValueError("Exactly one open market with that slug is required")
    m = matches[0]
    contract = contract_of(m)
    return {"contract": contract, "fingerprint": digest(contract), "state": {
        "active": m.state.active, "closed": m.state.closed, "archived": m.state.archived,
        "accepting_orders": m.state.accepting_orders, "enable_order_book": m.state.enable_order_book,
        "uma_status": str(m.resolution.uma_resolution_status) if m.resolution.uma_resolution_status else None,
    }, "market": m}


def draft_config(inspected: dict, *, kind: str = "manual", now: float | None = None, outcome: str = "YES", side: str = "BUY",
                 shares: str | None = None, limit_price: str = "0.50", max_cash: str | None = None) -> dict:
    """An intentionally unapproved template: the reader supplies semantic checks and limits.

    Without `shares` and `max_cash` the limits stay at zero, so the template cannot trade until the reader sets them.
    """
    now = time.time() if now is None else now
    c = inspected["contract"]
    return {
        "intent_id": str(uuid.uuid4()), "market_slug": c["slug"], "outcome": outcome, "side": side,
        "shares": "5" if shares is None else str(shares), "limit_price": str(limit_price), "expires_at": int(now) + 660, "post_only": False,
        "limits": {"max_cash": "0" if max_cash is None else str(max_cash), "max_shares": "0" if shares is None else str(shares),
                   "max_quote_age_seconds": 30},
        "approval": {"approved": False, "fingerprint": inspected["fingerprint"],
                     "reviewed_at": now, "valid_until": min(now + 3600, c["end_time"]),
                     "resolution_source": c["resolution_source"] or "",
                     "yes_definition": "", "note": ""},
        "strategy": {"kind": kind, "min_edge": 0.02 if kind != "manual" else 0, "inputs": {}},
    }


def build_preview(config: dict, inspected: dict, book, *, now: float | None = None) -> dict:
    """Calculate a plan using current public data. Rejected plans are never executable."""
    from .strategies import evaluate

    now = time.time() if now is None else now
    config_hash = digest(config)
    out = {"plan_id": config_hash[:16], "config_hash": config_hash, "intent_id": config.get("intent_id"),
           "eligible": False, "reasons": [], "contract_fingerprint": inspected["fingerprint"],
           "contract": inspected["contract"], "observed_at": now}
    reasons = out["reasons"]
    try:
        uuid.UUID(config["intent_id"])
        if config.get("demo") is True:
            raise ValueError("Synthetic demonstration configurations cannot be submitted")
        contract, state, approval, limits = inspected["contract"], inspected["state"], config["approval"], config["limits"]
        if config["market_slug"] != contract["slug"]:
            raise ValueError("Market slug mismatch")
        if approval.get("approved") is not True or approval.get("fingerprint") != inspected["fingerprint"]:
            raise ValueError("Review and approve the exact current contract; its fingerprint must match")
        reviewed = timestamp(approval["reviewed_at"], "reviewed_at")
        valid_until = timestamp(approval["valid_until"], "approval valid_until")
        if not reviewed <= now < valid_until <= reviewed + 86400:
            raise ValueError("Rule approval must be current and last at most 24 hours")
        for key in ("resolution_source", "yes_definition", "note"):
            if not isinstance(approval.get(key), str) or not approval[key].strip():
                raise ValueError(f"Rule approval needs a nonempty {key}")
        if contract["resolution_source"] and approval["resolution_source"] != contract["resolution_source"]:
            raise ValueError("Approved resolution source does not match the public contract")
        if state["active"] is not True or state["closed"] is not False or state["archived"] is not False:
            raise ValueError("Market is not explicitly active, open and unarchived")
        if state["accepting_orders"] is not True or state["enable_order_book"] is not True:
            raise ValueError("Market is not explicitly accepting book orders")
        if state["uma_status"] is not None:
            raise ValueError("A market in resolution or dispute is outside this toolkit's trading scope")
        if contract["neg_risk"] is not False or book.neg_risk is not False:
            raise ValueError("This first execution release supports ordinary binary markets; NegRisk scans remain read-only")
        if contract["version"] not in ("v1", "v2"):
            raise ValueError("The contract protocol version is unavailable or unsupported")
        outcome, side = config["outcome"], config["side"]
        if outcome not in ("YES", "NO") or side not in ("BUY", "SELL"):
            raise ValueError("outcome must be YES/NO and side BUY/SELL")
        if str(book.asset_id) != contract["tokens"][outcome] or str(book.condition_id) != contract["condition_id"]:
            raise ValueError("Order book belongs to a different contract or outcome")
        age_limit = timestamp(limits["max_quote_age_seconds"], "max_quote_age_seconds")
        if age_limit > 120:
            raise ValueError("Quote age limit cannot exceed 120 seconds")
        if book.timestamp is None or not -5 <= now - book.timestamp.timestamp() <= age_limit:
            raise ValueError("Order book timestamp is missing, stale or in the future")
        price = decimal(config["limit_price"], "limit_price")
        shares = decimal(config["shares"], "shares")
        tick = decimal(book.tick_size, "tick_size")
        minimum = decimal(book.min_order_size, "minimum order size")
        if not tick <= price <= 1 - tick or price % tick:
            raise ValueError("Limit price must fit the current tick grid")
        if shares < minimum or shares != shares.quantize(Decimal("0.01")):
            raise ValueError("Shares must meet the current minimum and have at most two decimals")
        if shares > decimal(limits["max_shares"], "max_shares"):
            raise ValueError("Share limit exceeded")
        expiration = config["expires_at"]
        if type(expiration) is not int or not now + 185 <= expiration <= contract["end_time"]:
            raise ValueError("GTD expiration needs 185 seconds of buffer and must not exceed the contract deadline")
        if expiration > valid_until:
            raise ValueError("The order must expire before its rule approval expires")
        if type(config["post_only"]) is not bool:
            raise ValueError("post_only must be boolean")
        sched = schedule_from_market(inspected["market"])
        if sched.taker_only is not True:
            raise ValueError("This execution release supports explicitly taker-only fee schedules")
        # A BUY can execute below its limit, where the fee can be larger. Reserve its maximum,
        # plus a five-decimal rounding buffer. Rebates are never counted before receipt.
        peak = min(price, Decimal("0.5")) if side == "BUY" else max(price, Decimal("0.5"))
        fee_unit_bound = Decimal(str(fee_per_share(float(peak), sched)))
        fee_bound = shares * fee_unit_bound + (Decimal("0.00001") if sched.rate else 0)
        cash_bound = shares * price + fee_bound if side == "BUY" else Decimal(0)
        decision_fee = fee_bound / shares
        if side == "BUY":
            # A BUY pays its fee in pUSD on top of price x shares and receives every matched share. For the
            # supported curves the all-in cost per share (price + fee) rises with the fill price, so the limit is worst.
            if sched.rate and (sched.rate > 1 or sched.exponent not in (1, 2)):
                raise ValueError("BUY execution requires a supported monotone fee curve (rate at most one, exponent one or two)")
            limit_fee_usd = shares * Decimal(str(fee_per_share(float(price), sched))) + (Decimal("0.00001") if sched.rate else 0)
            decision_fee = limit_fee_usd / shares
        if cash_bound > decimal(limits["max_cash"], "max_cash", positive=False):
            raise ValueError("Cash limit exceeded, including the conservative fee reserve")
        levels = book.asks if side == "BUY" else book.bids
        available = Decimal(0)
        visible_cash = Decimal(0)
        for level in sorted(levels, key=lambda x: x.price, reverse=side == "SELL"):
            p, qty = decimal(level.price, "book price"), decimal(level.size, "book size")
            if not 0 < p < 1:
                raise ValueError("Invalid book price")
            if (side == "BUY" and p > price) or (side == "SELL" and p < price):
                break
            take = min(qty, shares - available)
            available += take
            visible_cash += take * p
            if available == shares:
                break
        asks = sorted(book.asks, key=lambda x: x.price)
        bids = sorted(book.bids, key=lambda x: x.price, reverse=True)
        best_ask, best_bid = (str(asks[0].price) if asks else None), (str(bids[0].price) if bids else None)
        if config["post_only"] and available:
            raise ValueError("Post-only order would cross the currently displayed book")
        strategy = config["strategy"]
        if strategy.get("kind") in ("model_value", "favorite_carry"):
            if expiration > timestamp(strategy.get("inputs", {}).get("valid_until"), "forecast valid_until"):
                raise ValueError("The order must expire before its forecast expires")
        if strategy.get("kind") == "indexed":
            parameters = strategy.get("inputs", {}).get("parameters", {})
            if expiration > timestamp(parameters.get("valid_until"), "strategy inputs valid_until"):
                raise ValueError("The order must expire before its indexed inputs expire")
        if side == "SELL" and strategy.get("kind") != "manual":
            raise ValueError("Forecast strategy workflows open BUY positions; use manual SELL for an exit")
        decision = evaluate(strategy, outcome=outcome, limit_price=float(price),
                            fee_per_share=float(decision_fee), now=now,
                            end_time=contract["end_time"], resolution_source=approval["resolution_source"],
                            yes_definition=approval["yes_definition"], shares=float(shares))
        if decision.get("forecast_valid_until") is not None and expiration > timestamp(decision["forecast_valid_until"], "derived forecast valid_until"):
            raise ValueError("The order must expire before its derived forecast expires")
        reasons.extend(decision["reasons"])
        out.update({"order": {"token_id": contract["tokens"][outcome], "condition_id": contract["condition_id"],
                              "side": side, "size": str(shares), "price": str(price), "expiration": expiration,
                              "post_only": config["post_only"], "neg_risk": False, "version": contract["version"],
                              "fee_schedule": asdict(sched)},
                    "cash_bound": str(cash_bound), "fee_bound": str(fee_bound),
                    "quote": {"best_ask": best_ask, "best_bid": best_bid, "timestamp": book.timestamp.timestamp(),
                              "tick_size": str(tick), "min_order_size": str(minimum),
                              "immediately_available_shares": str(available),
                              "displayed_average_price": str(visible_cash / available) if available else None},
                    "decision": decision, "limits": limits,
                    "fee_model": {"buy_collection": "pUSD on top of price x shares", "sell_collection": "deducted from the pUSD proceeds",
                                  "order_and_matched_quantity": "shares matched; every matched share is delivered",
                                  "decision_fee_per_share": str(decision_fee)},
                    "warning": "Displayed liquidity can disappear. Unfilled quantities may rest. A BUY fee is paid in pUSD on top of price x shares and a SELL fee comes out of the proceeds; current holdings are separate from this order's fills. Fee reserves can differ from settlement rounding and later fees."})
        out["eligible"] = not reasons and decision["eligible"]
    except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation) as error:
        reasons.append(str(error) if isinstance(error, ValueError) else "Missing or invalid configuration/market data")
    return out


async def preview(config: dict, client=None, *, now: float | None = None) -> dict:
    if client is None:
        async with AsyncPublicClient() as public:
            return await preview(config, public, now=now)
    inspected = await inspect(config["market_slug"], client)
    outcome = config.get("outcome")
    if outcome not in ("YES", "NO"):
        raise ValueError("outcome must be YES or NO")
    book = await client.get_order_book(token_id=inspected["contract"]["tokens"][outcome])
    return build_preview(config, inspected, book, now=now)
