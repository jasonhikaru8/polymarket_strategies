"""Polymarket taker-fee, maker-rebate and taker-rebate-tier arithmetic.

Rates were checked against docs.polymarket.com in September 2026. Fees change often
(sports moved on 2026-07-10), so prefer a market's own schedule
(`market.trading.fee_schedule`, see `schedule_from_market`) over the table below.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class FeeSchedule:
    rate: float  # feeRate, e.g. 0.07 for crypto
    exponent: float = 1.0  # fee = shares * rate * (p * (1 - p)) ** exponent
    rebate_rate: float = 0.0  # share of taker fees redistributed to makers
    taker_only: bool = True


# category -> (taker feeRate, maker-rebate share). Geopolitics is fee-free.
CATEGORY_FEES: dict[str, tuple[float, float]] = {
    "crypto": (0.07, 0.20),
    "sports": (0.05, 0.15),
    "finance": (0.04, 0.25),
    "politics": (0.04, 0.25),
    "economics": (0.05, 0.25),
    "culture": (0.05, 0.25),
    "weather": (0.05, 0.25),
    "other": (0.05, 0.25),
    "mentions": (0.04, 0.25),
    "tech": (0.04, 0.25),
    "geopolitics": (0.0, 0.0),
}

# Taker Rebate Program (live 2026-05-28): (30-day weighted volume needed, tier, rebate)
TAKER_TIERS = [
    (0, "None", 0.00),
    (2_000, "Bronze", 0.03),
    (20_000, "Silver", 0.08),
    (200_000, "Gold", 0.18),
    (1_000_000, "Platinum", 0.32),
    (4_000_000, "Diamond", 0.44),
    (10_000_000, "Obsidian", 0.50),
]
CATEGORY_WEIGHTS = {
    "sports": 1.0,
    "politics": 1.3, "finance": 1.3, "mentions": 1.3, "tech": 1.3,
    "economics": 1.7, "culture": 1.7, "weather": 1.7, "other": 1.7,
    "crypto": 2.3,
    "geopolitics": 0.0,
}


def schedule_for(category: str) -> FeeSchedule:
    rate, rebate = CATEGORY_FEES[category.lower()]
    return FeeSchedule(rate=rate, rebate_rate=rebate)


def schedule_from_market(market) -> FeeSchedule:
    """Read an SDK market's fees; only explicitly disabled fees count as fee-free."""
    trading = getattr(market, "trading", None)
    enabled = getattr(trading, "fees_enabled", None)
    if enabled is False:
        return FeeSchedule(rate=0.0)
    sched = getattr(trading, "fee_schedule", None)
    if enabled is not True or sched is None:
        raise ValueError("market fee metadata is unavailable or inconsistent")
    try:
        rate, exponent = float(sched.rate), float(sched.exponent)
        rebate = float(sched.rebate_rate or 0)
        taker_only = sched.taker_only
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("market fee schedule is invalid") from error
    if (not all(isfinite(v) for v in (rate, exponent, rebate)) or rate < 0 or exponent < 0
            or not 0 <= rebate <= 1 or type(taker_only) is not bool):
        raise ValueError("market fee schedule is invalid")
    return FeeSchedule(rate, exponent, rebate, taker_only)


def fee_per_share(price: float, schedule: FeeSchedule) -> float:
    """Unrounded taker fee per share in USDC."""
    if (not all(isfinite(v) for v in (price, schedule.rate, schedule.exponent))
            or not 0 <= price <= 1 or schedule.rate < 0 or schedule.exponent < 0):
        raise ValueError("price must be in [0,1] and fee parameters finite and nonnegative")
    return schedule.rate * (price * (1 - price)) ** schedule.exponent


def taker_fee(shares: float, price: float, schedule: FeeSchedule) -> float:
    """Taker fee in USDC, rounded to 5 decimals as the platform does."""
    return round(shares * fee_per_share(price, schedule), 5)


def fee_fraction_of_cost(price: float, schedule: FeeSchedule) -> float:
    """Fee as a fraction of the price paid, e.g. about 0.0035 for crypto at 95c."""
    return fee_per_share(price, schedule) / price


def min_true_probability(price: float, schedule: FeeSchedule) -> float:
    """Chance the outcome must have, per share bought as a taker, to break even."""
    return price + fee_per_share(price, schedule)


def weighted_volume(trade_usdc: float, entry_price: float, category: str) -> float:
    """Weighted volume for the Taker Rebate Program: size x (1 - price) x category weight."""
    return trade_usdc * (1 - entry_price) * CATEGORY_WEIGHTS[category.lower()]


def tier_for(weighted_volume_30d: float) -> tuple[str, float]:
    """(tier name, rebate) for a 30-day weighted volume.

    Polymarket's help articles describe it as a portion of taker fees paid back to you.
    """
    name, rebate = "None", 0.0
    for need, tier, reb in TAKER_TIERS:
        if weighted_volume_30d >= need:
            name, rebate = tier, reb
    return name, rebate
