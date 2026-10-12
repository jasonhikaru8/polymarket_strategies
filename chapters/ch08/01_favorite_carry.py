"""Chapter 8, high-price carry: assumed price and fee, not a forecast. One win every 45 days compounds to 49% a year, as the chapter says."""
from polymarket_strategies.carry import annualized, return_if_win, wins_needed_per_loss
from polymarket_strategies.fees import FeeSchedule, fee_per_share

price, days = 0.95, 45
fee = fee_per_share(price, FeeSchedule(rate=0.04))
ret = return_if_win(price, fee)
print({"return_if_win": ret, "annualized_if_win": annualized(ret, days),
       "wins_canceled_by_one_loss": wins_needed_per_loss(price, fee)})
print("A loss can erase many wins; annualization assumes repeatable wins and reinvestment.")

