# Chapter 12: Strategy 19 (B5)

Run the synthetic demonstration:

```bash
uv run python chapters/ch12/strategy_19_B5_mention_markets.py
```

Expected: a finite JSON analysis with `eligible: true` and `order_authorized: false`. These numbers are invented. Repeat a historical group or include an outcome after as_of: the method rejects the sample.

Write the complete input schema to a new file and replace its evidence locally:

```bash
uv run polymarket-strategies strategy example 19 --out forecast-local.json
uv run python chapters/ch12/strategy_19_B5_mention_markets.py --inputs forecast-local.json
```

`--out` writes plain UTF-8 and never overwrites an existing file.

Keep the exact forecast YES definition and source aligned with the contract; supply real dated inputs, reviewed assumptions and your thresholds. Remove `demo: true` only after replacing the synthetic data.

For a supported order, follow [the indexed strategy workflow](../../STRATEGIES.md#prepare-a-supported-strategy-order). Preparation creates a fresh unapproved intent; you must complete the actual rules, limits and outcome review before `trade preview` and explicit submission. The full order lifecycle and private account setup are in [TRADING.md](../../TRADING.md). No chapter script places an order.
