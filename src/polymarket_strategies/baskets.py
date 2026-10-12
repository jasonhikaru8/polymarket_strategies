"""Walk several order books together to size a multi-leg basket at real depth (strategies A1 to A4).

The top of the book shows a price, not a size. This fills baskets level by level, checks aggregate
profit at the required minimum size, then stops when the next unit is no longer profitable.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from math import isfinite

from .fees import FeeSchedule, fee_per_share

Level = tuple[float, float]  # (price, size in shares)
_EPS = 1e-9  # dollars per basket: a smaller "profit" is floating-point noise (prices sit on a 0.001 grid and fees round to 0.00001)


def walk(legs: Sequence[Sequence[Level]], unit_profit: Callable[[Sequence[float]], float], min_size: float = 0.0) -> dict:
    """Check a minimum-size basket's total profit, then take profitable marginal units.

    `legs` holds each leg's levels ordered best price first. `unit_profit(prices)` is the profit per
    basket at those prices, after fees. `steps` lists each fill, so the walk can be shown line by line.
    `placeable` requires positive aggregate profit and enough equal shares for every leg.
    A losing marginal unit can complete a profitable minimum-size order. Below-minimum depth is
    still reported, but cannot be placed. This assumes best-first books and worsening unit profit.
    """
    if not legs or not isfinite(min_size) or min_size < 0:
        raise ValueError("a basket needs legs and a finite nonnegative minimum size")
    if any(not isfinite(p) or not 0 < p < 1 or not isfinite(s) or s <= 0 for leg in legs for p, s in leg):
        raise ValueError("book levels need finite prices in (0,1) and positive finite sizes")
    book = [[[p, s] for p, s in leg] for leg in legs]
    idx = [0] * len(book)
    sets = profit = 0.0
    steps: list[dict] = []
    while all(i < len(leg) for i, leg in zip(idx, book, strict=True)):
        prices = [leg[i][0] for i, leg in zip(idx, book, strict=True)]
        unit = unit_profit(prices)
        if not isfinite(unit):
            raise ValueError("basket profit must be finite")
        if unit <= _EPS and (sets == 0 or sets >= min_size):
            break
        qty = min(leg[i][1] for i, leg in zip(idx, book, strict=True))
        if unit <= _EPS:
            qty = min(qty, min_size - sets)
        steps.append({"prices": list(prices), "sets": qty, "profit_per_set": unit})
        sets += qty
        profit += qty * unit
        for k, leg in enumerate(book):
            leg[idx[k]][1] -= qty
            if leg[idx[k]][1] <= 1e-12:
                idx[k] += 1
    return {"sets": sets, "profit": profit, "profit_per_set": profit / sets if sets else 0.0, "steps": steps,
            "placeable": sets > 0 and sets >= min_size and profit > _EPS * sets}  # exclude round-off at breakeven


def buy_basket_profit(schedules: Sequence[FeeSchedule], payout: float = 1.0) -> Callable[[Sequence[float]], float]:
    """Profit per basket when you buy every leg as a taker and the basket pays at least `payout`."""
    def unit(prices: Sequence[float]) -> float:
        fees = sum(fee_per_share(p, s) for p, s in zip(prices, schedules, strict=True))
        return payout - sum(prices) - fees
    return unit


def sell_basket_profit(schedules: Sequence[FeeSchedule], payout: float = 1.0) -> Callable[[Sequence[float]], float]:
    """Profit per basket when you mint a set for `payout` (split) and sell every leg into bids as a taker."""
    def unit(prices: Sequence[float]) -> float:
        fees = sum(fee_per_share(p, s) for p, s in zip(prices, schedules, strict=True))
        return sum(prices) - fees - payout
    return unit
