"""Test a probability model against the market before trading it (strategy C1).

The lesson from the retired `weather-edge` bot: log prices for a few weeks, score the model
against the market, then simulate trades at the ask with fees. A model can be well
calibrated and still lose to a market that is better calibrated.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence

from .fees import FeeSchedule, fee_per_share

_EPS = 1e-9


def _check_forecasts(probs: Sequence[float], outcomes: Sequence[int]) -> None:
    if (not len(outcomes) or len(probs) != len(outcomes)
            or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs)
            or any(y not in (0, 1) for y in outcomes)):
        raise ValueError("forecasts need equal nonempty samples, finite probabilities in [0,1] and binary outcomes")


def log_loss(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    """Mean negative log-likelihood. Lower is better."""
    _check_forecasts(probs, outcomes)
    total = 0.0
    for p, y in zip(probs, outcomes, strict=True):
        p = min(max(p, _EPS), 1 - _EPS)
        total -= y * math.log(p) + (1 - y) * math.log(1 - p)
    return total / len(outcomes)


def brier(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    """Mean squared error of the probabilities. Lower is better."""
    _check_forecasts(probs, outcomes)
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes, strict=True)) / len(outcomes)


def compare(model: Sequence[float], market: Sequence[float], outcomes: Sequence[int]) -> dict[str, float]:
    """Scores for the model and the market on the same resolved questions."""
    return {
        "n": len(outcomes),
        "model_log_loss": log_loss(model, outcomes),
        "market_log_loss": log_loss(market, outcomes),
        "model_brier": brier(model, outcomes),
        "market_brier": brier(market, outcomes),
    }


def best_blend(model: Sequence[float], market: Sequence[float], outcomes: Sequence[int], step: float = 0.01) -> dict[str, float]:
    """Fit the weight minimizing log loss on these outcomes; reported scores are training scores.

    Evaluate the frozen weight on separate, later, event-grouped outcomes. Zero weight means no
    improvement within this linear blend and training sample. Grid default 0.01; ties favor the market.
    """
    if not math.isfinite(step) or not 0 < step <= 1:
        raise ValueError("blend step must be finite and in (0,1]")
    model_score = log_loss(model, outcomes)
    market_score = log_loss(market, outcomes)
    best_w, best_score = 0.0, market_score
    weights = [i * step for i in range(1, math.ceil(1 / step))] + [1.0]
    for w in weights:
        score = log_loss([w * m + (1 - w) * p for m, p in zip(model, market, strict=True)], outcomes)
        if score < best_score - 1e-12:
            best_w, best_score = w, score
    return {"weight_on_model": round(best_w, 4), "blend_log_loss": best_score, "market_log_loss": market_score,
            "model_log_loss": model_score}


def wilson_interval(successes: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """A 95% interval for a frequency (the Wilson score interval): how far a base rate seen `successes` times in `n` events can be trusted."""
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ValueError("n must be a positive whole number of events")
    if isinstance(successes, bool) or not isinstance(successes, (int, float)) or not math.isfinite(successes) or not 0 <= successes <= n:
        raise ValueError("successes must be a number between 0 and n")
    try:  # an integer too large for a float overflows in any of these divisions, not only the first
        p = successes / n
        centre = (p + z * z / (2 * n)) / (1 + z * z / n)
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    except OverflowError:
        raise ValueError("n is too large") from None
    # The exact interval always contains p and stays inside [0, 1]; floating-point round-off could push either end across (0 of 20 gave -1.4e-17).
    return max(0.0, min(p, centre - half)), min(1.0, max(p, centre + half))


def bootstrap_mean(values: Sequence[float], groups: Sequence[object] | None = None,
                   n_boot: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """(mean, 2.5th, 97.5th percentile) of the mean, resampling independent decisions.

    Pass `groups` (for example the parent event id) so linked trades count as one decision.
    """
    if groups is None:
        units = list(values)
    else:
        by_group: dict[object, float] = defaultdict(float)
        for v, g in zip(values, groups, strict=True):
            by_group[g] += v
        units = list(by_group.values())
    if not units or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in units):
        raise ValueError("a bootstrap needs a nonempty list of finite numbers")
    if isinstance(n_boot, bool) or not isinstance(n_boot, int) or n_boot < 20:
        raise ValueError("n_boot must be a whole number of at least 20")
    rng = random.Random(seed)
    n = len(units)
    means = sorted(sum(rng.choices(units, k=n)) / n for _ in range(n_boot))
    return sum(units) / n, means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def simulate_taker_trades(records: Sequence[dict], schedule: FeeSchedule, min_edge: float = 0.05) -> list[dict]:
    """Buy YES at the ask when model probability beats ask + fee by `min_edge`.

    Each record needs: `model_prob`, `ask` (the price you could actually pay), `outcome` (0 or 1),
    and optionally `group`. Returns per-trade net P&L per share.
    """
    if isinstance(min_edge, bool) or not isinstance(min_edge, (int, float)) or not math.isfinite(min_edge):
        raise ValueError("min_edge must be a finite number")
    trades = []
    for r in records:
        if r["outcome"] not in (0, 1) or isinstance(r["outcome"], bool) or not isinstance(r["model_prob"], (int, float)) or not 0 <= r["model_prob"] <= 1:
            raise ValueError("each record needs an outcome of 0 or 1 and a model_prob from 0 to 1")
        fee = fee_per_share(r["ask"], schedule)
        if r["model_prob"] - r["ask"] - fee >= min_edge:
            cost = r["ask"] + fee
            trades.append({"group": r.get("group"), "pnl": r["outcome"] - cost, "roi": (r["outcome"] - cost) / cost})
    return trades
