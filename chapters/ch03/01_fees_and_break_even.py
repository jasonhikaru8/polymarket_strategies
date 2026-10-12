"""Chapter 3, fees and break-even: assumed fee rate, not a live quote."""
from polymarket_strategies.fees import FeeSchedule, min_true_probability, taker_fee

schedule = FeeSchedule(rate=0.04)
print({"fee_for_100_shares": taker_fee(100, 0.95, schedule),
       "break_even_probability": min_true_probability(0.95, schedule)})

