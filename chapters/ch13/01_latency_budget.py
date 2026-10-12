"""Chapter 13, speed and cost budget: made-up clocks and executable ask."""
from polymarket_strategies.fees import FeeSchedule, fee_per_share

feed_delay, processing_delay, order_delay = 0.8, 0.2, 3.0
ask, estimated_probability = 0.80, 0.82
fee = fee_per_share(ask, FeeSchedule(rate=0.05))
print({"seconds_before_possible_fill": feed_delay + processing_delay + order_delay,
       "estimated_edge_after_entry_fee": round(estimated_probability - ask - fee, 4)})
print("Measure your own quote and clock. A historical stale quote does not prove it survived to your fill.")

