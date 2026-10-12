"""Chapter 7, a logically nested pair: the chapter's made-up quotes at the politics fee rate; verify the rules yourself."""
from polymarket_strategies.baskets import buy_basket_profit, walk
from polymarket_strategies.fees import FeeSchedule

# If smaller implies larger, YES(larger) + NO(smaller) pays at least $1. Party YES at 28 cents, Candidate NO at 68 cents.
print(walk([[(0.28, 100)], [(0.68, 100)]],
           buy_basket_profit([FeeSchedule(rate=0.04)] * 2), min_size=5))
print("The arithmetic cannot establish the logical implication or simultaneous execution.")
