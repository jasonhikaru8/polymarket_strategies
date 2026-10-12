"""Read a crypto market's price as a probability: option-implied chances, and the 60-second average that settles short markets.

Pure arithmetic, no network. The model is deliberately plain: a zero interest rate, a driftless price and one volatility. It is a way to
read prices and to spot when a comparison is wrong, not a trading model. Chapter 10 of the book explains each function with a toy and a
real example. The reader exercise is `chapters/ch10/01_crypto_probabilities.py`.
"""
from __future__ import annotations

from math import acos, erf, isfinite, log, pi, sqrt


def _check_model_inputs(spot: float, strike: float, vol: float, days: float) -> None:
    if (not all(isfinite(v) for v in (spot, strike, vol, days))
            or spot <= 0 or strike <= 0 or vol < 0 or days < 0):
        raise ValueError("spot and strike must be positive; volatility and days finite and nonnegative")


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + erf(x / sqrt(2)))


def digital_probability(spot: float, strike: float, vol: float, days: float) -> float:
    """Chance the price finishes ABOVE the strike on the date ('above X on date' markets): N(d2)."""
    _check_model_inputs(spot, strike, vol, days)
    if vol == 0 or days == 0:
        return float(spot > strike)
    t = days / 365
    s = vol * sqrt(t)
    return norm_cdf((log(spot / strike) - 0.5 * vol * vol * t) / s)


def _check_direction(direction: str) -> None:
    if direction not in ("up", "down"):
        raise ValueError("direction must be 'up' (reach at or above the strike) or 'down' (reach at or below it)")


def touch_probability(spot: float, strike: float, vol: float, days: float, *, direction: str = "up") -> float:
    """Chance the price touches the strike at some moment before the date, the starting price included.

    `direction="up"` asks for a touch at or above the strike ('hit $X' markets); `direction="down"` asks for a touch at or below it
    ('dip to $X' markets). A strike the price already stands beyond counts as touched (1.0). Otherwise the barrier is assumed
    untouched earlier in the contract. Choose the direction that matches the market's wording: the up formula gives a number
    above 1 for a strike below the spot.
    """
    _check_model_inputs(spot, strike, vol, days)
    _check_direction(direction)
    if spot >= strike if direction == "up" else spot <= strike:
        return 1.0
    if vol == 0 or days == 0:
        return 0.0
    t = days / 365
    s = vol * sqrt(t)
    d2 = (log(spot / strike) - 0.5 * vol * vol * t) / s
    if direction == "up":
        return norm_cdf(d2) + (spot / strike) * norm_cdf(d2 + s)
    return norm_cdf(-d2) + (spot / strike) * norm_cdf(-(d2 + s))


def implied_touch_vol(price: float, spot: float, strike: float, days: float, *, direction: str = "up") -> float:
    """Invert an untouched barrier (above the spot for "up", below it for "down") within 2% to 400% annual volatility.

    Reject targets outside this bracket, or cases where volatility is not identifiable.
    """
    _check_model_inputs(spot, strike, 0, days)
    _check_direction(direction)
    untouched = spot < strike if direction == "up" else spot > strike
    if not isfinite(price) or not 0 < price < 1 or not untouched or days == 0:
        raise ValueError("implied volatility requires a price in (0,1), an untouched barrier in the chosen direction and positive days")
    lo, hi = 0.02, 4.0
    if not touch_probability(spot, strike, lo, days, direction=direction) <= price <= touch_probability(spot, strike, hi, days, direction=direction):
        raise ValueError("no implied volatility in the supported 2% to 400% range")
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if touch_probability(spot, strike, mid, days, direction=direction) < price else (lo, mid)
    return (lo + hi) / 2


def call_spread_probability(cost_low_strike: float, cost_high_strike: float, width: float) -> float:
    """Buy the call at the lower strike, sell the call at the higher one. It pays `width` if the price ends above both strikes, nothing
    below the lower one, and the amount above the lower strike in between. Its cost over `width` is roughly the chance of finishing
    above the middle of the two strikes in a zero-rate dollar-priced model (exactly, the average risk-neutral
    terminal probability over the strikes between them). Inverse-settled options require a numeraire assumption."""
    if (not all(isfinite(v) for v in (cost_low_strike, cost_high_strike, width))
            or cost_high_strike < 0 or width <= 0 or not 0 <= cost_low_strike - cost_high_strike <= width):
        raise ValueError("call costs must be nonnegative and their difference between zero and the positive width")
    return (cost_low_strike - cost_high_strike) / width


def twap_disagreement(length_seconds: int, window_seconds: int) -> dict:
    """Chance that the winner under a snapshot rule (price at the start against price at the end) differs from the winner under an averaging
    rule (the average of the `window_seconds` ending at the start against the average of the `window_seconds` ending at the end), in a fair
    random walk with one-second steps.

    Cov(X_s, X_t) = min(s, t), so the correlation of the two changes is exact, and for two zero-mean normal changes the chance of opposite
    signs is arccos(correlation) / pi.
    """
    if any(type(v) is not int or v <= 0 for v in (length_seconds, window_seconds)):
        raise ValueError("length and window must be positive integer seconds")
    t0, t1 = window_seconds, window_seconds + length_seconds
    tick = {t1: 1.0, t0: -1.0}
    twap: dict[int, float] = {}
    for t in range(t1 - window_seconds + 1, t1 + 1):
        twap[t] = twap.get(t, 0) + 1 / window_seconds
    for t in range(1, window_seconds + 1):
        twap[t] = twap.get(t, 0) - 1 / window_seconds

    def cov(u, v):
        return sum(wu * wv * min(tu, tv) for tu, wu in u.items() for tv, wv in v.items())
    rho = cov(tick, twap) / sqrt(cov(tick, tick) * cov(twap, twap))
    rho = min(1.0, max(-1.0, rho))  # protect acos from floating-point roundoff
    return {"correlation": round(rho, 4), "disagree": round(acos(rho) / pi, 4)}


def twap_up_probability(known_sum: float, last_price: float, seconds_left: int, sigma_per_second: float, price_to_beat: float,
                        window: int = 60) -> float:
    """Chance the final window's average ends AT OR ABOVE the price to beat; ties go to Up.

    The average is (known prices + future prices) / window. Future prices follow a driftless walk from the last price, so the sum of the
    next n prices has mean n * last_price and variance sigma^2 * n (n + 1) (2n + 1) / 6.
    """
    if (type(window) is not int or window <= 0 or type(seconds_left) is not int or not 0 <= seconds_left <= window
            or not all(isfinite(v) for v in (known_sum, last_price, sigma_per_second, price_to_beat))
            or sigma_per_second < 0):
        raise ValueError("window and seconds left must be valid integer seconds; prices finite and volatility nonnegative")
    n = seconds_left
    mean = known_sum + n * last_price
    sd = sigma_per_second * sqrt(n * (n + 1) * (2 * n + 1) / 6)
    if sd == 0:
        return float(mean >= window * price_to_beat)
    return 1 - norm_cdf((window * price_to_beat - mean) / sd)
