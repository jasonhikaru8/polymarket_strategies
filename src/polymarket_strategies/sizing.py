"""Position sizing for binary contracts. This creates no edge: it limits ruin given an edge estimate."""
from __future__ import annotations

from math import isfinite

MAX_STREAK = 1000  # larger streaks and loss counts only overflow the arithmetic


def _number(value, name: str, low: float = 0.0, high: float | None = None) -> float:
    """A finite real number from `low` up to `high` (no upper bound when `high` is None); booleans and text are refused."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < low or (high is not None and value > high):
        raise ValueError(f"{name} must be a finite number " + (f"from {low:g} to {high:g}" if high is not None else f"of at least {low:g}"))
    return value


def kelly_fraction(true_prob: float, price: float, fee_per_share: float = 0.0) -> float:
    """Full-Kelly fraction of bankroll for buying a share that pays $1.

    Cost per share is c = price + fee. Maximizing q*ln(1 + f*(1/c - 1)) + (1-q)*ln(1 - f)
    gives f = (q - c) / (1 - c). Returns 0 when there is no edge.
    """
    _number(true_prob, "true_prob", 0, 1)
    _number(price, "price", 0, 1)
    _number(fee_per_share, "fee_per_share")
    cost = price + fee_per_share
    if not 0 < cost < 1:
        return 0.0
    return max(0.0, (true_prob - cost) / (1 - cost))


def fractional_kelly(fraction: float, multiple: float = 0.25, cap: float = 0.05) -> float:
    """Scale full Kelly down (default quarter Kelly) and cap the share of bankroll per position."""
    _number(fraction, "fraction", 0, 1)
    _number(multiple, "multiple", 0, 1)
    _number(cap, "cap", 0, 1)
    return min(fraction * multiple, cap)


def cap_clusters(fractions: dict[str, float], clusters: dict[str, str], cluster_cap: float) -> dict[str, float]:
    """Linked bets are one decision: scale positions so each cluster (for example one event) stays under the cap."""
    _number(cluster_cap, "cluster_cap")
    totals: dict[str, float] = {}
    for key, f in fractions.items():
        _number(f, f"the fraction for {key}")
        if key not in clusters:
            raise ValueError(f"{key} has no cluster; every position needs one")
        totals[clusters[key]] = totals.get(clusters[key], 0.0) + f
    return {
        key: f * min(1.0, cluster_cap / totals[clusters[key]]) if totals[clusters[key]] else 0.0
        for key, f in fractions.items()
    }


def martingale_exposure(base_bet: float, losses: int) -> tuple[float, float]:
    """(total lost so far, size of the next bet) after `losses` losses when the bet doubles each time."""
    _number(base_bet, "base_bet")
    if isinstance(losses, bool) or not isinstance(losses, int) or not 0 <= losses <= MAX_STREAK:
        raise ValueError(f"losses must be a whole number from 0 to {MAX_STREAK}")
    lost, next_bet = base_bet * (2**losses - 1), base_bet * 2**losses
    if not (isfinite(lost) and isfinite(next_bet)):
        raise ValueError("those numbers are too large to compute")
    return lost, next_bet


def expected_trades_to_losing_streak(streak: int, loss_prob: float = 0.5) -> float:
    """Expected number of independent trades until `streak` losses in a row (1/2 gives 2**(streak+1) - 2)."""
    if isinstance(streak, bool) or not isinstance(streak, int) or not 1 <= streak <= MAX_STREAK:
        raise ValueError(f"streak must be a whole number from 1 to {MAX_STREAK}")
    if isinstance(loss_prob, bool) or not isinstance(loss_prob, (int, float)) or not 0 < loss_prob < 1:
        raise ValueError("loss_prob must be a number between 0 and 1, not including either end")
    try:
        return (1 - loss_prob**streak) / ((1 - loss_prob) * loss_prob**streak)
    except (ZeroDivisionError, OverflowError):
        raise ValueError("that streak is too long to compute at this loss probability") from None
