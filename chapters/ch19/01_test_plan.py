"""Chapter 19, budget a paper test and cap related exposures: made-up planning inputs."""
from math import ceil

from polymarket_strategies.sizing import cap_clusters

planned_decisions, logging_weeks, bankroll = 300, 9, 1000  # the 90-day plan has nine logging weeks (63 days)
print({"decisions_per_week_needed": ceil(planned_decisions / logging_weeks),  # rounded up, as the chapter does: 34 a week reaches 300
       "decisions_per_logging_day": round(planned_decisions / (logging_weeks * 7), 2),
       "capped_paper_dollars": {key: bankroll * fraction for key, fraction in cap_clusters(
           {"a": 0.03, "b": 0.03, "c": 0.02},
           {"a": "event_a", "b": "event_a", "c": "event_b"}, 0.04).items()}})
print("300 is an illustrative checkpoint. Required evidence depends on dependence, precision and rare losses.")
