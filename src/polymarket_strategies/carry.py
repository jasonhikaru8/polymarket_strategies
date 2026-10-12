"""Carry arithmetic for high-probability positions and the holding-reward formula (strategy C8, C9)."""
from __future__ import annotations

from math import expm1, isfinite, log1p


def _number(value, name: str, low: float, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < low or (high is not None and value > high):
        raise ValueError(f"{name} must be a finite number " + (f"from {low:g} to {high:g}" if high is not None else f"of at least {low:g}"))
    return value


def _cost(price: float, fee_per_share: float) -> float:
    """Entry cost per share; it must leave room for the $1 payout."""
    cost = _number(price, "price", 0, 1) + _number(fee_per_share, "fee_per_share", 0)
    if not 0 < cost < 1:
        raise ValueError("entry cost including the fee must be above 0 and below the $1 payout")
    return cost


def return_if_win(price: float, fee_per_share: float = 0.0) -> float:
    """Return on cost if the share pays $1."""
    cost = _cost(price, fee_per_share)
    return (1 - cost) / cost


def annualized(period_return: float, days: float) -> float:
    """Compound annualized return for a return earned over `days`."""
    _number(period_return, "period_return", -1)
    if _number(days, "days", 0) == 0 or period_return == -1:
        raise ValueError("days must be positive, and a total loss cannot be annualized")
    try:
        result = expm1(log1p(period_return) * 365 / days)
    except OverflowError:
        result = float("inf")
    if not isfinite(result):
        raise ValueError("that period is too short to annualize into a meaningful number")
    return result


def wins_needed_per_loss(price: float, fee_per_share: float = 0.0) -> float:
    """How many wins one full loss cancels. At 97c one loss cancels about 32 wins."""
    cost = _cost(price, fee_per_share)
    return cost / (1 - cost)


def holding_reward_hourly(yes_shares: float, yes_mid: float, no_shares: float, no_mid: float,
                          annual_rate: float = 0.0325) -> float:
    """Hourly holding reward: position value x rate / 365 / 24.

    Position value counts YES shares at the YES mid and NO shares at the NO mid.
    The 3.25% rate is Polymarket's June 2026 figure; it is variable, so re-check it. Give it as a fraction: 0.0325, not 3.25.
    """
    for name, value in (("yes_shares", yes_shares), ("no_shares", no_shares)):
        _number(value, name, 0)
    for name, value in (("yes_mid", yes_mid), ("no_mid", no_mid), ("annual_rate", annual_rate)):
        _number(value, name, 0, 1)
    value = yes_shares * yes_mid + no_shares * no_mid
    return value * annual_rate / 365 / 24
