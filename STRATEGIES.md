# All 35 indexed strategy tools

> **Risk notice.** Trading prediction markets can lose all the money you put in. This software and the book are provided as is. The author is not responsible for any investment loss or other damage from using them; you use them entirely at your own risk. Nothing here is investment, legal or tax advice.

Every numbered strategy in the book has a runnable Python file. The filename contains both the book number and its original card ID: `strategy_07_C8_favorite_carry.py` is Strategy 7, card C8, in Chapter 8. The two practices and six not-to-do entries are outside these 35.

The small chapter files are entry points into three shared, tested implementation modules: `strategy_baskets.py`, `strategy_models.py` and `strategy_signals.py`. Read those modules to inspect the calculations. Use the complete package; copying just an entry file will not supply the toolkit.

## What has been implemented

All 35 tools analyze your documented inputs, print the calculations/assumptions and explain rejection reasons. Each has a complete synthetic input schema. Fifteen methods can feed a dated held-to-resolution forecast into the existing reviewed single-outcome order workflow. The other twenty implement basket analysis, timing/exit scenarios, quoting proposals, reward calculations, monitoring or exposure hedges. Their positive `eligible` flag means only that their stated analytical screen passed; `order_authorized` remains false. `eligible: null`, with a `decision_screen` note, means the tool has no pass/fail screen for those inputs: Strategy 26 (a monitor) always, and Strategy 33 without a calibrated election forecast. Treat anything other than `true` as not eligible.

This release does not run 35 unattended bots. Multi-leg execution needs equal leg sizes and management of stranded legs; cross-venue execution needs another authenticated exchange adapter; short-lived latency signals need a fast feed/executor; market making needs continuous inventory and cancellation management. Those systems are substantially harder than the decision mathematics and are not supplied here. The existing public scanners/quote watcher are available, but strategy inputs are not automatically harvested from weather services, sportsbooks, LLMs, polls or news feeds.

Evidence labels and reader review flags record assertions. They do not independently authenticate a forecast, establish profitability or verify historical comparability.

## Find your strategy

**Forecast → order** means a usable input-to-preview-to-explicit-order route for an eligible forecast. **Analysis/proposal** means the method has no automatic execution route in this package. Entry scripts themselves never authenticate or place an order.

| No. | ID | Chapter | Python entry file | Mode | Required evidence or data |
| --- | --- | --- | --- | --- | --- |
| 1 | A1 | 6 | [strategy_01_A1_binary_parity.py](chapters/ch06/strategy_01_A1_binary_parity.py) | Analysis/proposal | Both outcome books, current fees, exact binary-set rules |
| 2 | A2 | 6 | [strategy_02_A2_negrisk_bundles.py](chapters/ch06/strategy_02_A2_negrisk_bundles.py) | Analysis/proposal | Complete reviewed outcome universe, NegRisk conversion terms and every leg's fee |
| 3 | A3 | 7 | [strategy_03_A3_logical_arbitrage.py](chapters/ch07/strategy_03_A3_logical_arbitrage.py) | Analysis/proposal | Explicit logical implication, aligned rules and both books |
| 4 | A4 | 7 | [strategy_04_A4_date_ladder.py](chapters/ch07/strategy_04_A4_date_ladder.py) | Analysis/proposal | Common underlying event, ordered cutoffs, implication review |
| 5 | A5 | 7 | [strategy_05_A5_cross_venue.py](chapters/ch07/strategy_05_A5_cross_venue.py) | Analysis/proposal | Two venue books, payout/rule mapping, funding and disagreement stress |
| 6 | A6 | 7 | [strategy_06_A6_legged_accumulation.py](chapters/ch07/strategy_06_A6_legged_accumulation.py) | Analysis/proposal | Observed YES and NO inventory, incurred costs and an estimated completion rate |
| 7 | C8 | 8 | [strategy_07_C8_favorite_carry.py](chapters/ch08/strategy_07_C8_favorite_carry.py) | Forecast → order | Independent forecast/bounds, favorite threshold and horizon |
| 8 | C9 | 8 | [strategy_08_C9_holding_rewards.py](chapters/ch08/strategy_08_C9_holding_rewards.py) | Analysis/proposal | Verified reward eligibility, variable rate and opportunity cost |
| 9 | C4 | 8 | [strategy_09_C4_tail_ladder.py](chapters/ch08/strategy_09_C4_tail_ladder.py) | Analysis/proposal | Disjoint tail buckets, joint forecasts and uncovered scenarios |
| 10 | C1 | 9 | [strategy_10_C1_model_value.py](chapters/ch09/strategy_10_C1_model_value.py) | Forecast → order | Independent dated forecast with conservative bounds |
| 11 | C3 | 9 | [strategy_11_C3_weather_ensemble.py](chapters/ch09/strategy_11_C3_weather_ensemble.py) | Forecast → order | Station/measurement review, ensemble members, bias and stress allowance |
| 12 | C2 | 9 | [strategy_12_C2_llm_forecasts.py](chapters/ch09/strategy_12_C2_llm_forecasts.py) | Forecast → order | Sourced model forecasts, weights, human review and uncertainty allowance |
| 13 | C5 | 10 | [strategy_13_C5_options_value.py](chapters/ch10/strategy_13_C5_options_value.py) | Forecast → order | Aligned dollar call spread, payoff type (a touch market needs your own conversion), real-probability adjustment and stress bounds |
| 14 | C6 | 10 | [strategy_14_C6_twap_pricing.py](chapters/ch10/strategy_14_C6_twap_pricing.py) | Analysis/proposal | Actual averaging ticks/window, source, ties and price-walk uncertainty |
| 15 | B1 | 11 | [strategy_15_B1_news_catalysts.py](chapters/ch11/strategy_15_B1_news_catalysts.py) | Forecast → order | Archived public report plus a reviewed contract forecast |
| 16 | B2 | 11 | [strategy_16_B2_overreaction_fade.py](chapters/ch11/strategy_16_B2_overreaction_fade.py) | Forecast → order | Explicit resolution forecast for orders; exit-scenario mode is analysis only |
| 17 | B3 | 11 | [strategy_17_B3_macro_calendar.py](chapters/ch11/strategy_17_B3_macro_calendar.py) | Forecast → order | A released figure against its pre-release consensus, plus a calibrated contract forecast (a pre-release market-versus-benchmark gap is a `calc` check; see 17 below) |
| 18 | B4 | 11 | [strategy_18_B4_attention_rotation.py](chapters/ch11/strategy_18_B4_attention_rotation.py) | Forecast → order | Non-overlapping attention observations plus a reviewed forecast |
| 19 | B5 | 12 | [strategy_19_B5_mention_markets.py](chapters/ch12/strategy_19_B5_mention_markets.py) | Forecast → order | Previously resolved comparable independent events, for a per-word base rate (not the simple-word NO lead) |
| 20 | B6 | 12 | [strategy_20_B6_count_buckets.py](chapters/ch12/strategy_20_B6_count_buckets.py) | Forecast → order | Actual counter rules, observed count, pace and overdispersion stress |
| 21 | C10 | 12 | [strategy_21_C10_launch_fdv.py](chapters/ch12/strategy_21_C10_launch_fdv.py) | Analysis/proposal | Common launch/ladder identity, probabilities, deadlines and all rung books |
| 22 | D1 | 13 | [strategy_22_D1_crypto_latency.py](chapters/ch13/strategy_22_D1_crypto_latency.py) | Analysis/proposal | Source-matched feed/quote times, clock uncertainty and execution budget |
| 23 | D2 | 13 | [strategy_23_D2_sports_latency.py](chapters/ch13/strategy_23_D2_sports_latency.py) | Analysis/proposal | Confirmed sports observation, feed age, exchange delay and execution budget |
| 24 | D3 | 13 | [strategy_24_D3_oscillation_scalping.py](chapters/ch13/strategy_24_D3_oscillation_scalping.py) | Analysis/proposal | Entry/exit depth scenarios, both fees, slippage and exit horizon |
| 25 | B7 | 14 | [strategy_25_B7_resolution_rules.py](chapters/ch14/strategy_25_B7_resolution_rules.py) | Forecast → order | Open contract, documented source, rule checks and reviewed forecast |
| 26 | B8 | 14 | [strategy_26_B8_dispute_windows.py](chapters/ch14/strategy_26_B8_dispute_windows.py) | Analysis/proposal | Public proposal/challenge/phase data and estimated settlement lag |
| 27 | E1 | 15 | [strategy_27_E1_inventory_quotes.py](chapters/ch15/strategy_27_E1_inventory_quotes.py) | Analysis/proposal | Inventory, target/cap, fair value, tick grid and adverse selection |
| 28 | E2 | 15 | [strategy_28_E2_liquidity_rewards.py](chapters/ch15/strategy_28_E2_liquidity_rewards.py) | Analysis/proposal | Current eligibility, complementary score groups and pool assumptions |
| 29 | E3 | 15 | [strategy_29_E3_sportsbook_quotes.py](chapters/ch15/strategy_29_E3_sportsbook_quotes.py) | Analysis/proposal | Matched sportsbook event/rules, fresh odds, inventory and uncertainty |
| 30 | F1 | 16 | [strategy_30_F1_whale_copying.py](chapters/ch16/strategy_30_F1_whale_copying.py) | Analysis/proposal | One consistently selected wallet, complete prior positions and current target quote |
| 31 | F2 | 16 | [strategy_31_F2_wallet_flow.py](chapters/ch16/strategy_31_F2_wallet_flow.py) | Analysis/proposal | Reviewed condition-direction mapping, the wallet's trades and preselected alert thresholds |
| 32 | G1 | 17 | [strategy_32_G1_domain_expertise.py](chapters/ch17/strategy_32_G1_domain_expertise.py) | Forecast → order | Primary-source forecast, method and independent prior calibration record |
| 33 | G2 | 17 | [strategy_33_G2_polling.py](chapters/ch17/strategy_33_G2_polling.py) | Forecast → order | Poll design/precision, separately calibrated election forecast and full poll cost |
| 34 | G3 | 17 | [strategy_34_G3_public_information.py](chapters/ch17/strategy_34_G3_public_information.py) | Forecast → order | Archived public-source provenance and a reviewed contract forecast |
| 35 | H2 | 17 | [strategy_35_H2_exposure_hedge.py](chapters/ch17/strategy_35_H2_exposure_hedge.py) | Analysis/proposal | Existing real-world exposure, both outcomes and uncovered basis-risk scenarios |

## Run and change a method

Run a made-up demonstration without credentials:

```bash
uv run python chapters/ch09/strategy_10_C1_model_value.py
uv run polymarket-strategies strategy list
```

Write the complete JSON schema to a new file, edit it locally, then analyze it:

```bash
uv run polymarket-strategies strategy example 10 --out forecast-local.json
uv run python chapters/ch09/strategy_10_C1_model_value.py --inputs forecast-local.json
```

`--out` writes plain UTF-8 and never overwrites an existing file. (Avoid redirecting `--example` output with `>` on Windows PowerShell, which can write a different encoding.)

The general commands accept a book number or a card ID:

```bash
uv run polymarket-strategies strategy example C1
uv run polymarket-strategies strategy analyze 10 forecast-local.json
```

Every emitted example has `demo: true` and invented data. Replace the data, definitions, sources, timestamps and review flags with real evidence. Remove the demo marker only after that work. `strategy prepare` and the trading bridge reject an untouched marked example and any input that still contains the examples' placeholder text (`example.invalid` or `SYNTHETIC`). `strategy analyze` (and an entry file's `--inputs`) reports such an input as `eligible: false` and `synthetic: true` once the demo marker is gone; with the marker it still shows the demonstration. `as_of` must already exist; `valid_until` must remain current. Output describes assumptions rather than promising an edge. A rejected analysis prints diagnostic JSON; it has made no order attempt.

**Units and fees.** Prices are dollars per share, between 0 and 1. Every fee is cash: a BUY pays its price plus the fee per share and receives every matched share; a SELL receives its price minus the fee per share. The standard taker fee per share is `rate × price × (1 − price)`; maker orders pay none. For example, 5 shares bought at $0.50 with a $0.01 fee per share cost $2.55 and deliver 5 shares: $0.51 a share. `fee_per_share` is that cash fee at your limit price; the trading preview supplies the current one, and actual rounding can differ slightly. Quantities (`shares`, `quantity`, depth, inventory, order and trade sizes, `hedge_shares`, `planned_shares`) are plain share counts. Basket tools test one `min_profit` in total dollars for the whole basket; the other tools test `min_edge` in dollars per share. Probabilities, vote shares and annual rates are fractions (0.04 means 4%); only Strategy 28's spreads are in cents. Times are Unix seconds (UTC); durations are in seconds unless the field name ends in `_hours` or `_days`. [Fees](https://docs.polymarket.com/trading/fees)

## Input fields

`strategy example N` prints a complete input for method N; the tables say what each field means. A field is required unless the table gives a default or a condition. Flags described as `true` must be the JSON value `true`: they record your own checks, which the tool cannot verify.

### Basket tools: Strategies 1 to 6, 9 and 21

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `as_of`, `valid_until` | Unix s | yes | When the snapshot was taken (not in the future, at most `max_age_seconds` old) and when it expires (after now) |
| `max_age_seconds` | s | default 60 | Oldest acceptable snapshot, 1 to 120; applies to the input and to each leg |
| `shares` | shares | yes | Order quantity on every leg |
| `max_cash` | USD | yes | Cash limit for the modeled cost |
| `min_profit` | USD, total | default 0 | The basket's floor (or expected) profit must exceed it |
| `review` | `true` flags | yes | `rules`, `source` and `timing`, plus each strategy's flags below |
| `legs` | list | yes | The leg objects below (Strategy 21 puts them inside `rungs`) |

| Leg field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `market_id` | text | yes | The market; for Strategies 2 and 9, the outcome's identifier as listed in `universe` |
| `outcome` | `YES`/`NO` | yes | The token this leg trades |
| `definition`, `source` | text | yes | The leg's YES definition and resolution source |
| `cutoff` | Unix s | yes | The contract's deadline, in the future |
| `as_of`, `valid_until` | Unix s | yes | This leg's book snapshot time and expiry, as above |
| `book` | `[[price, shares], ...]` | yes | Displayed levels, best first: asks rising for a BUY leg, bids falling for a SELL leg |
| `min_size` | shares | yes | Venue minimum order size; `shares` must reach it |
| `fee` | object | yes | `rate` (fraction, e.g. 0.04), `exponent` (1 for the standard schedules), `taker_only` (true or false), `flat_per_share` (USD a share, default 0) |
| `fee_collection` | `cash` | yes | Must be `cash`: a BUY fee is paid on top of the price and a SELL fee comes out of the proceeds |
| `slippage_per_share` | USD a share | default 0 | Extra cost reserved on a BUY, or deducted from a SELL |
| `usd_per_unit` | USD per venue unit | default 1 | Currency conversion; required by Strategy 5, and only Strategy 5 may use a value other than 1 |
| `event_id` | text | Strategies 2, 9, 21 | The event; must match on every leg |

**1 (A1).** Review `binary_complete_set`; `mint_sell_set` also needs `mint_route` and `inventory_and_collateral`. One YES and one NO leg of the same market (equal `market_id`, `source`, `cutoff`, `definition`).

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `mode` | text | default `buy_set` | `buy_set` buys both legs at their asks; `mint_sell_set` mints sets at $1 each and sells both legs into their bids |
| `conversion_cost_usd` | USD, total | for `mint_sell_set`; default 0 otherwise | Minting or conversion cost beyond the $1 collateral per set |

**2 (A2).** Review `universe_complete`, `exclusive`, `exhaustive`, `fixed_outcomes`, `negrisk_link`; `convert_no` also needs `conversion_route` and `inventory_and_collateral`. One leg per outcome, equal `event_id`, `source` and `cutoff`.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `mode` | text | default `buy_yes_bundle` | `buy_yes_bundle` (every leg YES; a set pays $1), `buy_no_bundle` (every leg NO; a set pays $1 × (outcomes − 1)) or `convert_no` |
| `universe` | list of text | yes | Every outcome's `market_id`, each once |
| `source_outcome` | text | for `convert_no` | The outcome whose NO you buy (a NO leg with an ask book); every other leg is a YES leg with a bid book, sold after the conversion |
| `conversion_cost_usd` | USD, total | default 0 | Conversion cost |

**3 (A3).** Review `implication`. Legs: the larger (implied) event's YES, then the smaller (implying) event's NO, in different markets with equal `source` and `cutoff`.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `implication_evidence` | text | yes | Why the smaller event implies the larger one |
| `conversion_cost_usd` | USD, total | default 0 | Any extra cost |

**4 (A4).** Review `implication`, `same_event`, `deadline_nesting`. Legs: the later date's YES, then the earlier date's NO, in different markets with equal `source`; the earlier leg's `cutoff` must come first. Their `definition` texts differ by date and are listed in the output.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `underlying_event_id` (each leg) | text | yes | Your identifier for the same event criterion; must match on both legs even when their `event_id`s differ |
| `conversion_cost_usd` | USD, total | default 0 | Any extra cost |

**5 (A5).** Review `equivalence`, `void_rules`, `payout_timing`, `access`, `currency`, `costs`. Legs: venue A's YES, then venue B's NO, with equal `source`, `cutoff` and `definition`. Each leg's `fee` states that venue's fee, paid in cash.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `venue` (each leg) | text | yes | Two different venue names |
| `payout_usd_floor` (each leg) | USD a share | yes | The least a winning share pays after conversion; at most `usd_per_unit` |
| `harmful_mismatch_probability_upper` | fraction | yes | Upper bound on the chance the venues resolve so that both legs lose |
| `beneficial_mismatch_probability_lower` | fraction | default 0 | Lower bound on the chance both legs win; the two chances add to at most 1 |
| `mismatch_evidence` | text | yes | Basis for those chances |
| `funding_and_withdrawal_usd` | USD, total | yes | Transfer costs |
| `maximum_lock_days` | days | yes | Longest time the capital stays locked; must cover the time to `cutoff` |
| `funding_annual_rate` | fraction a year | yes | Cost of the locked capital, 0 to 1 |

**6 (A6).** Review `binary_complete_set`, `maker_fees`, `completion_model`, `inventory`. Legs: YES then NO of one market; `fee.taker_only` must be true and `flat_per_share` 0, because a maker pays no fee. `book` is not used.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `limit_price` (each leg) | dollars | yes | Your resting maker bid |
| `queue_ahead` (each leg) | shares | yes | Shares queued ahead of you (reported only) |
| `completion_probability_lower` | fraction | yes | Conservative chance both bids fill |
| `completion_evidence` | text | yes | Basis for it |
| `stranded_loss_per_share` | USD a share | yes | Loss on a share when only one leg fills |
| `max_stranded_loss_usd` | USD | yes | Most you accept to hold unpaired |
| `inventory` | object | yes | What you already hold: `yes_shares`, `no_shares` (shares) and `yes_cost_usd`, `no_cost_usd` (USD paid) |

**9 (C4).** Review `universe_complete`, `exclusive`, `exhaustive`, `forecast`. Legs: at least two different YES buckets from `universe`, with equal `event_id`, `source` and `cutoff`.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `universe` | list of text | yes | Every bucket's `market_id` |
| `coverage_probability_lower` | fraction | yes | Conservative chance the winner is one of your buckets |
| `forecast_evidence` | text | yes | Basis for it |
| `max_bucket_price` | dollars | default 0.10 | Highest price any filled level may have |

**21 (C10).** Review `launch_definition`, `fdv_measurement`, `deadline_nesting`, `forecast`.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `launch_probability`, `launch_probability_lower` | fraction | yes | Chance of a qualifying launch, and its conservative lower bound |
| `forecast_evidence` | text | yes | Basis for the forecasts |
| `rungs` | list | at least 2 | Rungs with rising `threshold_usd`, each with the fields below |
| `threshold_usd` | USD of FDV | yes | The rung's valuation threshold |
| `conditional_probability`, `conditional_probability_lower` | fraction | yes | Chance of clearing the threshold given a launch, and its lower bound; neither may rise with the threshold |
| `leg` | leg object | yes | The rung's YES leg, plus `launch_id` and `event_id` (text, equal on every rung); `source` and `cutoff` must match; `definition` differs by threshold |
| `no_book` | `[[price, shares], ...]` | every rung above the lowest | The rung's NO asks, for nested pairs (a lower rung's YES plus a higher rung's NO) |

### Forecast, model and signal tools: Strategies 7, 8, 10 to 20 and 22 to 35

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `target_yes_definition` | text | yes | The YES outcome your evidence concerns; must equal `contract.yes_definition` |
| `resolution_source` | text | yes | Must equal `contract.resolution_source` |
| `evidence`, `source_notes` | text | yes | What the evidence is and where it came from |
| `as_of`, `valid_until` | Unix s | yes | When the evidence or forecast was made (not in the future) and when it expires (after now) |
| `contract` | object | yes | `yes_definition`, `resolution_source` and `end_time` (Unix s, after now; Strategy 26 may be past it); Strategy 30 also needs `market_id` and `event_id` |
| `outcome` | `YES`/`NO` | yes | The side you would buy |
| `limit_price` | dollars | yes | Your price, between 0 and 1 |
| `fee_per_share` | USD a share | yes | Cash fee per share at that price, paid on top; price plus fee must stay below $1 |
| `min_edge` | USD a share | yes | Smallest acceptable edge after the fee. For a position held to a distant resolution, include the cash the price could earn meanwhile (price × yearly cash rate × days ÷ 365; the book's Appendix D) |
| `probability_yes`, `conservative_low_yes`, `conservative_high_yes` | fraction | Strategies 7, 10, 15 to 18, 25, 32 to 34 ("forecast fields") | Your YES forecast and conservative bounds (low ≤ forecast ≤ high); a YES decision uses the low bound, a NO decision one minus the high bound |

For the fifteen forecast → order methods, the trading bridge replaces `contract`, `outcome`, `limit_price` and `fee_per_share` with the inspected market and the order, and applies the stricter of the plan's and the inputs' `min_edge`. Some tools check envelope fields they do not use: `min_edge` (Strategies 8, 26, 28, 30, 31, 35), `limit_price` (27, 28, 29, 31), `fee_per_share` (26 to 29, 31) and `outcome` (22 to 24, 26 to 28, 31; Strategies 22 to 24 take the probability and prices of the outcome you name). Enter real values anyway.

**7 (C8).** Forecast fields, plus:

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `min_favorite_price` | dollars | yes | Lowest price you treat as a favorite, from 0.5 to below 1 |
| `min_expected_annual_return` | fraction a year | yes | Required conservative expected return on cost, scaled by 365/days without compounding |
| `max_days` | days | yes | Longest time to `end_time` you accept |

**8 (C9).** The screen needs a positive estimated net: expected payout − cost + rewards − alternative return.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `reward_eligibility_verified` | `true` | yes | The market currently pays holding rewards to you |
| `reward_terms_source` | text | yes | Where the terms are published |
| `reward_rate_annual` | fraction a year | yes | Reward rate, 0 to 1 (0.0325 is 3.25%) |
| `midpoint` | dollars | yes | Midpoint of the outcome you hold (the NO midpoint for a NO position) |
| `shares` | shares | yes | Shares held |
| `holding_days` | days | yes | How long the cash is committed; must cover the time to `end_time`. Rewards stop at `end_time`; the alternative return is charged for all of it |
| `probability_yes` | fraction | yes | Your YES probability (one minus it for NO) |
| `alternative_rate_annual` | fraction a year | yes | What the cash would earn elsewhere, 0 to 1 |
| `actual_rewards_received` | USD | yes | Rewards received so far (reported, not used) |

**10 (C1).** Forecast fields only.

**11 (C3).**

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `measurement_reviewed` | `true` | yes | Station, units, local date and settlement measurement checked |
| `station_id` | text | yes | The settlement station |
| `members` | list of numbers | at least 2 | Ensemble forecasts of the settlement value, in the station's units |
| `bucket_lower`, `bucket_upper` | station units | yes | A member counts when `bucket_lower ≤ member < bucket_upper`. For a 78–79°F bucket settled in whole degrees, enter 77.5 and 79.5; a member at exactly 79.5 counts in the next bucket only |
| `probability_bias_adjustment` | fraction | yes | Added to the members' share, −1 to 1; the result is kept within 0 to 1 |
| `uncertainty_allowance` | fraction | yes | Positive half-width of the stress bounds |

**12 (C2).**

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `human_reviewed` | `true` | yes | You reviewed each model's sources and reasoning |
| `calibration_notes` | text | yes | How the models' calibration was checked |
| `forecasts` | list | yes | Each: `model` (unique text), `probability_yes` (fraction), `weight` (0 or more; the total must be above 0), `source` (text) |
| `uncertainty_allowance` | fraction | yes | Positive half-width of the stress bounds |

**13 (C5).** A call spread's cost ÷ width is roughly a finish-above (terminal) chance: that the price ends above the middle of the two strikes on the expiry date. Say which question the market asks. A **finish above** market uses that reference. A **range** market (the price ends between two levels) subtracts a second spread's reference, taken at the range's upper level. A **touch** market ("hit $X" at any moment before the date) is refused unless you supply your own `touch_probability`, because terminal option prices do not determine a touch chance; for a price with no trend, a touch is about twice as likely as finishing above (Chapter 10). `crypto_pricing.touch_probability` gives one model's number. The tool reports `option_implied_reference`, `payoff_type` and `payoff_reference` (the number your `probability_adjustment` is added to).

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `option_contract_match_reviewed`, `risk_neutral_to_real_reviewed` | `true` | yes | Expiry, underlying, settlement, currency, payoff type (finish above, touch or range) and observation window match; risk-neutral pricing reviewed |
| `payoff_type` | text | yes | `finish_above`, `touch` or `range`: what YES pays on |
| `conversion_notes` | text | yes | How you turn the option price into an actual probability |
| `call_low_cost`, `call_high_cost` | price units | yes | Call prices at the lower and higher strike; the difference is between 0 and `strike_width` (for a range, the spread at the range's lower level) |
| `strike_width` | price units | yes | Distance between the strikes, above 0 |
| `upper_call_low_cost`, `upper_call_high_cost`, `upper_strike_width` | price units | `range` | The same three for a call spread at the range's upper level; its reference may not exceed the first one's |
| `touch_probability` | fraction | `touch` | Your touch chance for YES, 0 to 1, converted from the options (for example with `touch_probability`); it replaces the finish-above reference |
| `touch_conversion_notes` | text | `touch` | How you converted: the model, the starting price, the volatility, the dates and the direction (`up` for "hit", `down` for "dip") |
| `probability_adjustment` | fraction | yes | Added to `payoff_reference` (from pricing chances to actual chances), −1 to 1; the result must stay within 0 to 1 |
| `conservative_low_yes`, `conservative_high_yes` | fraction | yes | Bounds around the adjusted probability |

**14 (C6).** YES is Up: the window's average ends at or above `price_to_beat`. The screen requires the model probability of `outcome` minus `limit_price` and `fee_per_share` to reach `min_edge` (a point probability, without stress bounds).

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `settlement_window_reviewed` | `true` | yes | Source, averaging ticks, window and tie rule checked |
| `window_seconds`, `seconds_left` | s, integers | yes | The averaging window and the part still to come |
| `observed_prices` | list, price units | yes | Exactly `window_seconds − seconds_left` prices already in the window |
| `last_price` | price units | yes | Latest price, where the remaining walk starts (normally the last observed price) |
| `sigma_per_second` | price units | yes | Standard deviation of a one-second price change |
| `price_to_beat` | price units | yes | The reference price |

**15 (B1).** Forecast fields, plus (`as_of` must not precede `report.received_at`):

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `report` | object | yes | `url` (http or https), `summary`, `archive_sha256` (64 lowercase hexadecimal characters of your saved copy), `publicly_accessible` and `provenance_reviewed` (`true`), `published_at` ≤ `received_at` ≤ now (Unix s) |
| `report_matches_contract_reviewed` | `true` | yes | The report concerns this contract's event |

**16 (B2).** `outcome` must be NO.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `pre_news_yes`, `spike_yes` | dollars | yes | YES price before the news and at the spike (0 ≤ before < spike < 1) |
| `mode` | text | yes | `held_to_resolution` (forecast → order) or `exit_mark` (analysis only) |
| `resolution_forecast_reviewed` | `true` | `held_to_resolution` | Plus the forecast fields |
| `rumor_confirmation_probability` | fraction | `exit_mark` | Chance the rumor is confirmed |
| `exit_yes_if_confirmed`, `exit_yes_if_denied` | dollars | `exit_mark` | The YES price you expect at your exit in each case |
| `exit_fee_if_confirmed`, `exit_fee_if_denied` | USD a share | `exit_mark` | Cash fee per share on the exit SELL in each case |
| `slippage_reserve` | USD a share | `exit_mark` | Extra exit cost |

**17 (B3).** What this tool models: the surprise in a scheduled release that has already happened. It records when the consensus was fixed, when the figure was released and when you received it, reports the surprise (actual − consensus) and the surprise ÷ `surprise_scale`, and then screens your own calibrated forecast for the contract. It does not compare a market with a benchmark. Chapter 11's B3, comparing Polymarket's price for a scheduled event with a public benchmark probability for the same event before the outcome (for example a FedWatch-style probability), needs no special tool: run `calc` with the market's fee rate, the ask as `--price` and your benchmark probability as `--prob` (Chapter 11's toy: `calc --rate 0.05 --price 0.53 --prob 0.60` gives a fee of 1.25 cents a share and a break-even of 0.5425, so the benchmark's 60% is worth about 5.75 cents a share if it is right), and keep your benchmark readings in the paper journal. Forecast fields, plus:

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `benchmark_fixed_at`, `release_at`, `actual_received_at` | Unix s | yes | benchmark < release ≤ receipt ≤ `as_of` |
| `actual`, `consensus` | release units | yes | Released value and the consensus fixed before it |
| `surprise_scale` | release units | yes | Positive scale for the standardized surprise |
| `release_units` | text | yes | For example, percentage points |
| `contract_response_model_reviewed` | `true` | yes | Your forecast maps the surprise to this contract |

**18 (B4).** Forecast fields, plus:

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `attention_model_reviewed` | `true` | yes | |
| `min_rate_ratio` | ratio | yes | Smallest current ÷ baseline rate you accept, above 0 |
| `baseline_period`, `current_period` | objects | yes | Each `start`, `end` (Unix s; `end` after `start` and not after `as_of`) and `count` (integer); the baseline ends before the current period starts |

**19 (B5).** What this tool models: a per-word base rate, as in Chapter 12's base-rate toy. It computes how often the word was said (the YES frequency) across your comparable, previously resolved events, with Wilson 95% bounds, and screens your side's price against that. It does not implement the simple-word NO lead that Chapter 12 reports as its exploratory result (a subgroup found after several unplanned splits); test that with a fixed rule on later events in the paper log of Chapter 12's Try It on Paper. No forecast fields:

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `cohort` | text | yes | The reviewed comparable cohort |
| `comparability_reviewed` | `true` | yes | |
| `min_events` | integer | yes | Your planned minimum number of events, at least 2 |
| `events` | list | yes | Each: `event_id` and `group` (unique; one group per independent speech), `outcome_yes` (true or false), `resolved_at` (Unix s, before `as_of`), and `cohort`, `resolution_source`, `yes_definition` equal to the top-level values |

**20 (B6).** The probability is a negative-binomial count with mean pace × days and variance multiplier × mean; `normal_approximation_probability` reports Chapter 12's bell curve for comparison only (it is unreliable when few posts remain).

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `settlement_counter_reviewed` | `true` | yes | Counting source, included posts, time zone and window checked |
| `model_notes` | text | yes | |
| `observed_count` | integer | yes | Count so far in the window |
| `count_lower`, `count_upper` | integers | yes | The bucket's final-count bounds, both included; `count_upper` is null for an open top bucket |
| `days_remaining` | days | yes | Time left, above 0 and within the contract |
| `pace_per_day` | posts a day | yes | Expected future rate |
| `variance_multiplier` | ratio | yes | Variance of the future count ÷ its mean, at least 1 (1 is Poisson) |
| `stress_paces`, `stress_variances` | lists | yes | Paces and multipliers (at least 1) to stress for the bounds; the main pace and multiplier are always included, and a repeated value counts once |
| `uncertainty_allowance` | fraction | yes | Positive amount added outside the stress range |

The spread matters as much as the pace. The example's multiplier of 6 is Chapter 12's illustration, not an estimate: in the book's weekly count data the trailing pace missed the final count by 40 posts on average with four days left, which implies a multiplier of about 16 to 22. So the example stresses multipliers of 6, 16 and 24 (`variance_multiplier` 6, `stress_variances` [6, 16, 24]). Estimate the multiplier from past windows of the same account, and treat a bucket whose verdict changes across plausible multipliers as no trade.

**22 (D1) and 23 (D2).** The delays must end before the opportunity does, and probability − price − fee must reach `min_edge`.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `reference_matches_contract`, `observation_confirmed` | `true` | yes | The feed is the contract's reference and the event is confirmed |
| `event_at`, `feed_received_at` | Unix s | yes | event ≤ receipt ≤ `as_of` |
| `quote_at`, `max_quote_age_seconds` | Unix s, s | yes | Quote time (not after `as_of`) and freshness limit |
| `execution_latency_seconds` | s | yes | Your time to get an order matched, above 0 |
| `clock_uncertainty_seconds` | s | yes | Clock error allowance |
| `opportunity_expires_at` | Unix s | yes | When the opportunity ends; not after `end_time` |
| `conservative_outcome_probability` | fraction | yes | Conservative probability of `outcome` |
| `sports_order_delay_seconds` | s | Strategy 23 | The exchange's delay on sports orders |

**24 (D3).**

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `entry_ask` | dollars | yes | Entry price, at most `limit_price` |
| `planned_exit_bid` | dollars | yes | The bid you plan to sell into |
| `exit_fee_per_share` | USD a share | yes | Cash fee per share on the exit SELL |
| `slippage_reserve` | USD a share | yes | |
| `quantity` | shares | yes | Planned size |
| `entry_depth`, `exit_depth_estimate` | shares | yes | Depth at entry and expected at exit; each must cover `quantity` |
| `quote_at`, `max_quote_age_seconds` | Unix s, s | yes | |
| `exit_deadline`, `max_holding_seconds` | Unix s, s | yes | Latest exit: within `max_holding_seconds` of now and not after `end_time` |

**25 (B7).** Forecast fields, plus:

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `source_document` | object | yes | Strategy 15's `report` fields plus `source_id`, equal to `resolution_source`; `received_at` not after `as_of` |
| `contract_status` | text | yes | Must be `open` |
| `rule_review` | object | yes | `source_match`, `timezone`, `units`, `cutoff`, `ties`, `exceptions`, all `true` |

**26 (B8).** A monitor with no pass/fail screen: `eligible` is null and `decision_screen` says so.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `phase` | text | yes | `open`, `proposed`, `disputed`, `voting` or `resolved`. Public statuses: initialized or posed → `open`; proposed or reproposed → `proposed` (enter the latest proposal's times); challenged or disputed → `disputed`; a vote in progress → `voting`. Map any other status yourself |
| `proposal_at`, `challenge_deadline` | Unix s | yes; null when `open` | The latest proposal (not after `as_of`) and its challenge deadline |
| `settlement_eta` | Unix s | yes | Your estimate of settlement |
| `status_source` | text | yes | Where you read the status |

**27 (E1).** Both quotes' edges after fee and adverse selection must reach `min_edge`.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `fair_outcome_probability` | fraction | yes | Your fair value of the outcome token |
| `half_spread` | dollars | yes | Distance of each quote from the inventory-adjusted center, above 0 |
| `inventory`, `target_inventory`, `max_inventory` | shares | yes | Shares held, the level you aim for, and the cap |
| `inventory_price_per_share` | dollars a share | yes | How far the center moves per share away from the target |
| `bid_size`, `ask_size` | shares | yes | Quote sizes; the ask cannot exceed `inventory` |
| `tick_size` | dollars | yes | Price grid, below 1 |
| `best_bid`, `best_ask` | dollars | yes | The current book; your quotes must not cross it |
| `quote_at`, `max_quote_age_seconds` | Unix s, s | yes | |
| `bid_fill_fee_per_share` | USD a share | yes | Cash fee per share if your bid fills (0 for a maker fill on a taker-only schedule; enter a reserve if unsure) |
| `ask_fill_fee_per_share` | USD a share | yes | Cash fee per share taken from the proceeds if your ask fills |
| `adverse_selection_per_fill` | USD a share | yes | Expected loss per fill to better-informed takers |

**28 (E2).** An order at or beyond `max_spread_cents`, or below `minimum_size`, fails the screen.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `program_active`, `rewards_eligible` | `true` | yes | The market is in the program and your orders qualify |
| `minimum_size` | shares | yes | The program's minimum order size |
| `max_spread_cents` | cents | yes | The program's maximum distance from the size-adjusted midpoint |
| `size_adjusted_midpoint` | dollars | yes | The program's midpoint; one-sided quoting scores only between 0.10 and 0.90 |
| `orders` | list | yes | Each: `id` (unique), `score_side` (`one` = YES bids and NO asks; `two` = YES asks and NO bids), `spread_cents` (cents from the midpoint), `size` (shares of the resting order) |
| `snapshot_total_min_score` | score | yes | All makers' score in the snapshot, yours included |
| `reward_pool_usdc` | USD | yes | The pool for the period |
| `reward_window_seconds` | s | yes | The pool's period (checked, not used) |
| `assumed_trading_loss_usdc` | USD | yes | Trading loss you expect while quoting |

**29 (E3).** Strategy 27's fields, with the sportsbook's de-vigged probability for `outcome` in place of `fair_outcome_probability`, plus:

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `same_event_reviewed`, `settlement_rules_match` | `true` | yes | |
| `sportsbook_source` | text | yes | |
| `sportsbook_as_of`, `max_sportsbook_age_seconds` | Unix s, s | yes | Odds time (not after `as_of`) and freshness limit |
| `yes_decimal_odds`, `no_decimal_odds` | decimal odds | yes | Above 1; the margin is removed in proportion |
| `sportsbook_probability_uncertainty` | fraction | yes | Taken off each side's edge before the `min_edge` test |

**30 (F1).** `limit_price` + `fee_per_share` − the target's cash per share must not exceed `max_copy_price_premium`, and depth must cover `copy_size`.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `history_complete_reviewed`, `open_and_closed_positions_included`, `target_identity_reviewed` | `true` | yes | |
| `selected_wallet` | text | yes | The wallet chosen before the target trade |
| `target_market_id`, `target_event_id` | text | yes | Equal to `contract.market_id` and `contract.event_id` |
| `selection_fixed_at` | Unix s | yes | When you fixed the selection; before the target trade |
| `training_trades` | list | yes | The wallet's trade objects up to `selection_fixed_at`, oldest first |
| `training_positions` | list | yes | Each: `id`, `observed_at` (Unix s, up to `selection_fixed_at`), `event` (each once), `wallet`, `status` (OPEN, CLOSED or MIXED), `total_pnl` (USD) |
| `target_trade` | trade object | yes | The trade to copy: a BUY of `outcome` after the selection, plus `market_id`, `outcome`, `target_yes_definition` and `resolution_source` matching yours |
| `quote_at`, `max_quote_age_seconds` | Unix s, s | yes | |
| `copy_size`, `available_depth` | shares | yes | Your size and the depth at your price |
| `max_copy_price_premium` | USD a share | yes | Most you will pay above the wallet's cost per share |

Trade objects (Strategies 30 and 31): `id` (unique), `timestamp` (Unix s), `event`, `wallet`, `side` (BUY or SELL), `size` (shares), `price` (dollars) and `cash_notional_usdc` (dollars: size × price, within 2 cents a share for the fee plus 1 cent of rounding; a BUY may include its fee and a SELL may be net of it; amounts in cents or base units are rejected).

**31 (F2).** The alert fires only when every threshold is met; it does not identify an insider.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `wallet_label` | text | yes | |
| `wallet_created_at` | Unix s | yes | Not after `as_of`; no trade before it |
| `economic_direction_definition` | text | yes | What a positive direction means |
| `condition_mappings` | list | yes | Each: `condition_id` (unique), `event`, `theme`, `yes_direction` (POSITIVE or NEGATIVE: whether YES moves your direction up), `reviewed` (`true`) |
| `lookback_seconds` | s | yes | Every trade must fall within this window before now |
| `max_wallet_age_hours` | hours | yes | Oldest wallet that still counts as fresh |
| `min_notional_usdc` | USD | yes | Smallest total cash that alerts |
| `min_theme_share`, `min_direction_share` | fraction | yes | Thresholds for the largest theme's share of the cash, and for the dominant net direction's share of all shares traded (`observed_share_flow`) |
| `trades` | list | yes | Trade objects, oldest first, each with `condition_id`, `theme` and `outcome` (YES or NO) |

**32 (G1).** Forecast fields, plus the fields below. The screen needs at least `min_decisions` records and a Brier score below 0.25, the score of always forecasting 50%.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `domain`, `method` | text | yes | |
| `calibration_reviewed` | `true` | yes | |
| `min_decisions` | integer | yes | The record size you planned in advance, at least 2; the book treats 100 and 300 as checkpoints |
| `calibration_records` | list | at least 2 | Each: `event_id`, `group` (unique), `probability_yes` (fraction), `outcome_yes` (true or false), `forecast_at` < `resolved_at` < now (Unix s), `resolved_at` not after `as_of` |

**33 (G2).** Without `election_model_reviewed: true` the result is descriptive (`eligible` null).

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `sample_size` | interviews | yes | Integer, at least 2 |
| `share_a`, `share_b` | fraction | yes | Two candidates' shares, together at most 1 |
| `design_effect` | ratio | yes | At least 1 (1.5 widens the interval by about 22%) |
| `election_model_reviewed` | `true` | for a decision | |
| `calibration_notes`, forecast fields | text, fractions | for a decision | Your separately calibrated election forecast |
| `poll_cost` | USD, total | for a decision | Spread over `planned_shares` |
| `planned_shares` | shares | for a decision | The order bridge replaces it with the order's size |

**34 (G3).** Strategy 15's fields, plus `duty_restricted` and `can_influence_outcome`, which must both be `false`.

**35 (H2).** The premium, `hedge_shares` × (`limit_price` + `fee_per_share`), must not exceed `max_hedge_cost`, and the worst loss must fall by at least `min_worst_loss_reduction`.

| Field | Unit | Required | Meaning |
| --- | --- | --- | --- |
| `exposure_description` | text | yes | |
| `hedge_shares` | shares | yes | Shares of `outcome` to buy, above 0 |
| `max_hedge_cost` | USD | yes | Largest premium you accept |
| `min_worst_loss_reduction` | USD | yes | Smallest acceptable cut in the worst scenario loss |
| `scenarios` | list | at least 2 | Each: `scenario_id` (unique), `real_world_loss` (USD), `contract_yes` (true or false); include both contract outcomes and the uncovered cases |

## Prepare a supported strategy order

For a **Forecast → order** method, inspect the actual contract, then prepare a new unapproved intent:

```bash
uv run polymarket-strategies trade inspect MARKET_SLUG --out inspected-local.json
uv run polymarket-strategies strategy prepare 10 forecast-local.json inspected-local.json --out trade-local.json --min-edge 0.02
```

Or use its indexed chapter file:

```bash
uv run python chapters/ch09/strategy_10_C1_model_value.py --inputs forecast-local.json --trade-config inspected-local.json --out trade-local.json --min-edge 0.02
```

Preparation first runs the method's own analysis with the stricter of `--min-edge` and the `min_edge` in your inputs (0.02 when neither is given), and refuses inputs that fail it. It then generates a new intent ID, resets approval, preserves your caps and restricts expiry to the input/approval window. It creates no order and refuses to overwrite an existing file. Complete the contract review and set the outcome, price, shares and caps (`trade inspect` takes `--outcome`, `--shares`, `--price` and `--max-cash`, so the inspected file you prepare from already carries them), then approve in your terminal with `trade approve trade-local.json`, which keeps this strategy's own YES definition when you press Enter. Following [TRADING.md](TRADING.md), you can also edit the approval by hand.

```bash
uv run polymarket-strategies trade preview trade-local.json
```

The preview recomputes the indexed method with the current approved contract/source, selected outcome, actual limit, current modeled fee and minimum edge. It replaces cached financial/contract context from the input file, so old cheap quotes cannot support a new expensive order. Poll costs are spread over the order's share quantity, because every matched share is delivered; the reported total-strategy edge includes that cost. The order must expire before the forecast, approval and contract. A late TWAP or sub-minute latency signal cannot fit the existing GTD minimum lifetime. [GTD requirements](https://docs.polymarket.com/trading/place-orders)

Only after an eligible preview and your deliberate acceptance, use the explicit submission/status/cancel/recovery commands in [TRADING.md](TRADING.md). Only ordinary non-NegRisk binary markets with supported, explicitly taker-only fee curves can use this adapter. Strategy 16 needs its held-to-resolution mode; its hypothetical exit-mark mode supplies no order forecast. Strategy 33 needs a separately calibrated election forecast; a poll's lead/confidence interval alone is insufficient. Strategy 25 cannot trade markets already in resolution or dispute.

For **Analysis/proposal** methods, the CLI rejects order-plan preparation. Their output includes quantities, legs, quotes, scenarios or alerts to inspect. This prevents a multi-leg plan or an unverified timing scenario from being presented as a supported one-leg trading strategy.
