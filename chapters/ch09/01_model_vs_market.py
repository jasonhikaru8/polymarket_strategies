"""Chapter 9, train a blend then score separate events: tiny made-up samples."""
from polymarket_strategies.edge_check import best_blend, compare

training_model, training_market, training_outcomes = [0.9, 0.1, 0.9, 0.1], [0.5] * 4, [1, 0, 1, 0]
weight = best_blend(training_model, training_market, training_outcomes)["weight_on_model"]
later_model, later_market, later_outcomes = [0.9, 0.1, 0.9, 0.1], [0.5] * 4, [0, 0, 1, 1]
blend = [weight * m + (1 - weight) * p for m, p in zip(later_model, later_market)]
print({"frozen_training_weight": weight, "later_scores": compare(blend, later_market, later_outcomes)})
print("Good training scores do not establish performance on later events or after trading costs.")

