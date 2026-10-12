"""Chapter 15, liquidity-reward score: made-up eligible quotes, not a reward forecast."""
from polymarket_strategies.reward_score import min_score, side_score

one = side_score(3, [(1, 100), (2, 200), (1, 100)])
two = side_score(3, [(1.5, 100), (2, 100), (0.5, 200)])
print({"side_one": one, "side_two": two, "qualifying_score": min_score(one, two, 0.50)})
print("Actual qualification, competing liquidity, fill losses and pool changes remain unmeasured here.")

