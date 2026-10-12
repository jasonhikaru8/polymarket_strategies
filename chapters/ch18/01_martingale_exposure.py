"""Chapter 18, why doubling losses is ruinous: arithmetic only, no trading system."""
from polymarket_strategies.sizing import expected_trades_to_losing_streak, martingale_exposure

lost, next_bet = martingale_exposure(10, 6)
print({"lost_after_six_losses": lost, "next_bet": next_bet,
       "expected_trades_to_seven_losses_at_half": expected_trades_to_losing_streak(7)})
print("Doubling does not create an edge; a bankroll limit prevents an unlimited recovery sequence.")

