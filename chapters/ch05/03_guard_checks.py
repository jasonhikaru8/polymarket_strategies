"""Chapter 5, demonstrate the live-order guard and a size cap without network access or an account.

The trading toolkit applies the same guard before it submits an order. It bounds each order with the `limits.max_cash` and
`limits.max_shares` in the order's config; `cap_size` below is the simple version of that idea.
"""
from polymarket_strategies.safety import NotAllowed, cap_size, require_live

try:
    require_live(False, blocked=False)
except NotAllowed as error:
    print(str(error))
print({"requested_dollars": 500, "cap_dollars": cap_size(500, 25)})
print("This offline guard demonstration places no orders.")
