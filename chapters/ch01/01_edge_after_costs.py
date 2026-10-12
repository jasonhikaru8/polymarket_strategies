"""Chapter 1, edge after costs: made-up probabilities and prices."""
from polymarket_strategies.fees import FeeSchedule, fee_per_share

probability, midpoint, ask = 0.52, 0.50, 0.505
fee = fee_per_share(ask, FeeSchedule(rate=0.05))
result = {"gross_edge": probability - midpoint,
          "edge_after_spread_and_fee": probability - ask - fee,
          "break_even_probability": ask + fee}
print({key: round(value, 6) for key, value in result.items()})  # six decimals, as `calc` prints: no floating-point noise
