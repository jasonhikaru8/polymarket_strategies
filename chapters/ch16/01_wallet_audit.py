"""Chapter 16, a synthetic wallet record: no real address or identifiable account."""
from polymarket_strategies.wallet_audit import audit

trades = [{"side": "BUY", "size": 100, "price": 0.97, "event": f"made-up-{i}"} for i in range(10)]
positions = [{"total_pnl": 3.0}] * 9 + [{"total_pnl": -97.0}]
print(audit(trades, positions))
print("A wallet summary is a screen, not evidence of identity, wrongdoing or copyable skill.")

