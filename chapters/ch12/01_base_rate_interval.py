"""Chapter 12, uncertain base rates: made-up successes across independent events."""
from polymarket_strategies.edge_check import wilson_interval

successes, events = 6, 10
print({"observed_frequency": successes / events, "wilson_95_interval": wilson_interval(successes, events)})
print("A word, count or launch model also needs matching definitions and later-event testing.")

