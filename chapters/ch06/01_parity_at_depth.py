"""Chapter 6, walking a pair of books: the chapter's made-up quotes at a 0.05 fee rate, no order placement."""
from polymarket_strategies.baskets import buy_basket_profit, walk
from polymarket_strategies.fees import FeeSchedule

yes_asks = [(0.44, 100), (0.46, 200)]
no_asks = [(0.50, 150), (0.52, 300)]
print(walk([yes_asks, no_asks], buy_basket_profit([FeeSchedule(rate=0.05)] * 2), min_size=5))
print("Displayed books can change between legs; this arithmetic is not a guaranteed fill.")
