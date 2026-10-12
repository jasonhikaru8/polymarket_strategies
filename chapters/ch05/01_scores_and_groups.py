"""Chapter 5, scoring and grouped results: tiny made-up samples, no evidence of skill."""
from polymarket_strategies.edge_check import bootstrap_mean, compare

print(compare([0.9, 0.1, 0.8, 0.9], [0.6, 0.4, 0.6, 0.6], [1, 0, 1, 1]))
print({"grouped_mean_and_interval": bootstrap_mean(
    [1, 1, -3, 2], groups=["event_a", "event_a", "event_b", "event_c"])})
print("Three events are too few to establish an edge; this only demonstrates grouping.")

