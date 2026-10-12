"""Chapter 10, model assumptions for terminal, touch and average rules: the chapter's made-up inputs."""
from polymarket_strategies.crypto_pricing import digital_probability, touch_probability, twap_disagreement, twap_up_probability

print({"terminal_above": round(digital_probability(100_000, 110_000, 0.50, 30), 4),  # finish above $110,000 in 30 days
       "touch_up_before_end": round(touch_probability(100_000, 110_000, 0.50, 30), 4),  # touch $110,000 at any moment
       "touch_down_before_end": round(touch_probability(100_000, 90_000, 0.50, 30, direction="down"), 4),  # a "dip to $90,000" market
       "average_ends_at_or_above": round(twap_up_probability(known_sum=40 * 100.00, last_price=99.98, seconds_left=20,
                                                              sigma_per_second=0.02, price_to_beat=100.00), 4),
       "snapshot_vs_average": twap_disagreement(300, 60)})
print("These zero-rate, driftless model probabilities are not real-world forecasts or live prices.")
