"""Chapter 4, sizing and linked exposures: made-up inputs, not an edge estimate."""
from polymarket_strategies.sizing import cap_clusters, fractional_kelly, kelly_fraction
from polymarket_strategies.fees import FeeSchedule, fee_per_share

price, probability = 0.52, 0.60
fee = fee_per_share(price, FeeSchedule(rate=0.07))
full = kelly_fraction(probability, price, fee_per_share=fee)
print({"full_kelly": full, "quarter_kelly_capped": fractional_kelly(full)})
print(cap_clusters({"a": 0.03, "b": 0.03, "c": 0.02},
                   {"a": "same_event", "b": "same_event", "c": "other_event"}, 0.04))
