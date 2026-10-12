"""Chapter 17, hedge cash flows: made-up exposure and binary payout, before fees."""
shares, ask = 100, 0.40
premium = shares * ask
for event_happens, existing_loss in [(True, 100), (False, 0)]:
    payout = shares if event_happens else 0
    print({"event_happens": event_happens, "existing_loss": existing_loss,
           "net_cash_flow_with_hedge": payout - premium - existing_loss})
print("A mismatch between the contract and the actual exposure creates basis risk; price that separately.")

