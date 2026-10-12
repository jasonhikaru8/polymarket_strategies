"""Chapter 2, one complete YES/NO set: the chapter's real 37-cent bid and made-up $100 trader, with the taker fee."""
from polymarket_strategies.fees import FeeSchedule, taker_fee

cash, yes_bid = 100.0, 0.37
split = 10  # splitting $10 creates 10 YES and 10 NO shares
sports = FeeSchedule(rate=0.05)
cash_after_split = cash - split
fee = taker_fee(split, yes_bid, sports)  # selling the 10 YES into the 37-cent bid as a taker: 10 x 0.05 x 0.37 x 0.63
cash_after_sale = cash_after_split + split * yes_bid - fee
print({"cash_after_split": cash_after_split, "taker_fee": fee, "cash_after_selling_yes": round(cash_after_sale, 2),
       "cash_at_end_if_NO_wins": round(cash_after_sale + split, 2),   # the 10 NO shares pay $10
       "cash_at_end_if_YES_wins": round(cash_after_sale, 2)})         # the 10 NO shares pay nothing
