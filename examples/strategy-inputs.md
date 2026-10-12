# Trade-config strategy objects: C1, C8 and B5

This file documents the original strategy objects that sit in the `strategy`
field of a trade config: `trade inspect MARKET_SLUG --strategy model_value`
(or `favorite_carry`, `mention_base_rate`, `manual`) writes one with empty
`inputs` for you to fill in. The 35 numbered strategy tools, including the
chapter files for Strategies 7, 10 and 19, use a different, flat input schema:
print it with `--example` (or `strategy example N`), and see
[STRATEGIES.md](../STRATEGIES.md) for every field.

The decision code accepts your evidence; it does not invent forecasts, retrieve
the book's private research, or assert that a strategy is profitable. The order
workflow separately approves the exact contract, reads its quote and fee,
enforces caps, and checks orders and fills. These objects assume a binary
outcome held to resolution. Unusual refunds, partial payouts and early exits
need their own payoff model.

## Shared configuration

Every strategy is an object with `kind`, `inputs` and a required `min_edge` in
dollars per share. `min_edge` must be finite and nonnegative. A decision is
eligible only if the conservative outcome probability exceeds the limit price
plus the entry fee by at least that margin. The entry fee is the cash fee per
share at the limit price: a BUY pays it on top of the price and receives every
matched share. Buy NO uses `1 - probability_yes` and `1 - conservative_high_yes`,
because the upper YES bound is the conservative NO case. Eligibility here passes
only the decision calculation.

`evaluate` receives the selected outcome (`YES` or `NO`), limit price, entry fee
per share, current Unix timestamp, contract end timestamp, approved literal
`yes_definition`, and approved `resolution_source`. Prices and total entry cost
(price plus fee) must be strictly between $0 and $1; fees cannot be negative.
The contract must end in the future. Returned fields are `probability`,
`conservative_probability`, `edge_per_share`, `eligible`, `reasons`, and
`assumption`. Rejected inputs give `eligible: false` with the reason; a missing
field is never silently defaulted.

## C1: model value

Use `kind: "model_value"`. Required `inputs`:

| Field | Meaning |
| --- | --- |
| `probability_yes` | Your independent estimate, in [0, 1] |
| `conservative_low_yes`, `conservative_high_yes` | Conservative bounds containing the estimate, in [0, 1] |
| `as_of`, `valid_until` | Unix timestamps; `as_of <= now < valid_until` |
| `target_yes_definition` | Exact match to the approved YES definition |
| `resolution_source` | Exact match to the approved source |
| `evidence`, `source_notes` | Nonempty descriptions of evidence and provenance |

The program checks bounds and freshness, not the accuracy or independence of your
estimate. Fit and freeze a model before scoring later events. Selecting a
probability merely because it produces an attractive edge is not forecasting.

## C8: favorite carry

Use `kind: "favorite_carry"` and supply all C1 fields plus:

| Field | Meaning |
| --- | --- |
| `min_favorite_price` | Minimum purchase price, at least 0.5 and below 1 |
| `min_expected_annual_return` | Required nonnegative conservative expected annual return, e.g. 0.10 for 10% |
| `max_days` | Positive maximum scheduled days to resolution |

Expected annual return is `(conservative_probability - price - fee) / (price +
fee) * 365 / days`. This simple scale uses no assumed compounding. It is expected
return under your forecast, not the return conditional on winning. Actual
settlement delays, a wrong forecast, and rare total losses can defeat the screen.

## B5: mention base rate

Use `kind: "mention_base_rate"`. Required `inputs` are `target_yes_definition`,
`resolution_source`, `evidence`, `source_notes`, a nonempty `cohort` description,
`comparability_reviewed: true`, integer `min_events >= 2`, and an `events` list.
Each historical event must contain:

```json
{
  "event_id": "your-resolved-event-id",
  "group": "your-independent-speech-id",
  "outcome_yes": true,
  "resolved_at": 1799900000,
  "cohort": "your-reviewed-comparable-cohort",
  "resolution_source": "your-reviewed-resolution-source",
  "yes_definition": "your-reviewed-YES-definition"
}
```

All events must resolve strictly before the decision. Event IDs and groups must
be unique, outcomes must be true/false, and cohort/source/definition must match
the declared inputs. Several words or markets from one speech cannot be counted
as independent events. The estimate is the historical YES frequency; its
conservative bounds are a Wilson 95% interval. The interval does not correct
selection bias, changed topics, changed speakers, dependence, or a mismatch in
the current contract. Review comparability and rejected events yourself;
matching text labels cannot establish those facts. `min_events` is your sample
requirement, not a universal assurance of adequate evidence.

## Manual decision

`{"kind": "manual", "min_edge": 0, "inputs": {}}` deliberately supplies no
forecast. The result has null probabilities and edge, and identifies the manual
assumption. Contract approval, fresh quotes, caps and order handling still apply.
The manual mode requires `min_edge: 0` because it cannot check a probability margin.
