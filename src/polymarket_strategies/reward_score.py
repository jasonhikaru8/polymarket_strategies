"""Liquidity-rewards scoring, following the formula on docs.polymarket.com/programs/liquidity-rewards.

Spreads are in cents from the size-adjusted midpoint. The book is sampled once a minute;
this scores one sample. Read-only: it screens, it never places orders.
"""
from __future__ import annotations

SCALING_C = 3.0  # single-sided scaling factor (docs: 3.0 on all markets)


def order_score(max_spread: float, spread: float, multiplier: float = 1.0) -> float:
    """S(v, s) = ((v - s) / v)^2 * b for orders inside the qualifying spread, else 0."""
    if spread >= max_spread or spread < 0:
        return 0.0
    return ((max_spread - spread) / max_spread) ** 2 * multiplier


def side_score(max_spread: float, orders: list[tuple[float, float]]) -> float:
    """Sum of score x size over (spread, size) orders."""
    return sum(order_score(max_spread, s) * size for s, size in orders)


def min_score(q_one: float, q_two: float, midpoint: float, c: float = SCALING_C) -> float:
    """Two-sided quoting is rewarded fully; one side counts at 1/c, and only if the midpoint is in [0.10, 0.90]."""
    two_sided = min(q_one, q_two)
    if 0.10 <= midpoint <= 0.90:
        return max(two_sided, max(q_one / c, q_two / c))
    return two_sided


def share_of_pool(my_q: float, all_q: float, pool_usdc: float) -> float:
    """Rough daily reward if your average normalized score were `my_q / all_q` of `pool_usdc`."""
    return pool_usdc * my_q / all_q if all_q else 0.0
