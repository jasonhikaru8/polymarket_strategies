# Reader-code release manifest

Reader package for *35 Polymarket Strategies, Graded by Evidence*, version 0.5.0.

**Included:** all 35 indexed strategy entry files (named with the book number and the original card ID), 21 general section exercises across 19 chapters, three shared strategy implementation modules, public market-data tools, arithmetic calculators, a paper journal and its spreadsheet template (`templates/paper-journal.csv`), the reader-controlled trading toolkit, synthetic input schemas, offline tests, dependency files and the MIT license. `STRATEGIES.md` has the complete chapter mapping and every input field; `CHANGES.md` lists what changed in this version.

**What the strategy tools do:** fifteen methods support a reviewed held-to-resolution forecast-to-order workflow. Twenty supply basket calculations, timing and exit scenarios, quote proposals, reward estimates, monitoring or exposure-hedge analysis without strategy execution. An eligible analysis is not order authorization, and a tool that applies no screen reports `eligible: null`. The package does not run 35 unattended bots or collect the external evidence the methods require.

**The trading toolkit** sets up your account values once (`trade setup`, with an optional private credentials file) and checks that the account is ready (`trade check`), inspects public rules, checks explicit reader approval and dated strategy inputs, previews current quotes and modeled fees, asks for a typed confirmation, submits an expiring limit order and reconciles actual orders and trades into a persistent local ledger. It supports ordinary non-NegRisk binary markets whose outcomes are labeled Yes and No, with supported taker-only fee curves. A BUY fee is paid in pUSD on top of price x shares and every matched share is delivered; a SELL fee comes out of the proceeds. Strategy orders are BUYs; a reviewed manual SELL can close a holding. The ledger and the `KILL` file live in `~/.polymarket-strategies/`. Modeled fee reserves can differ from the platform's partial-fill rounding.

**Excluded:** figure-generation code, full research collectors, frozen raw snapshots, real-wallet dumps, bulk study rows, private publication tools, secrets, local trade plans and ledgers, and local environments. Examples use invented data and are marked as demonstrations.

**Validation:** a fresh offline dependency installation of version 0.4.0 succeeded with Python 3.13 and the pinned `polymarket-client` 0.11.0. For version 0.5.0, all 1265 offline tests passed with Python 3.13 and `polymarket-client` 0.12.0 (9 October 2026, and again on 12 October 2026 with Python 3.13 and with Python 3.11; 0.4.4 passed 1215 and 0.4.3 passed 1214 on 7 October; 0.4.2 passed 1212 on 5 October; 0.4.1 passed 1204 with Python 3.11 and 0.11.0), including all 56 chapter scripts (Chapter 14's original resolution watcher: its help screen only), all 35 strategy schemas, contract and event identity checks, cash-fee regressions, the book's printed toy numbers, and simulated end-to-end order and fill workflows for all 15 supported forecast methods. Forecast accuracy, economic profitability and trading eligibility are not established by these checks.

## Files

- `.gitignore`
- `CHANGES.md`
- `LICENSE`
- `README.md`
- `RELEASE_MANIFEST.md`
- `STRATEGIES.md`
- `TRADING.md`
- `chapters/ch01/01_edge_after_costs.py`
- `chapters/ch02/01_complete_set.py`
- `chapters/ch03/01_fees_and_break_even.py`
- `chapters/ch04/01_fractional_kelly.py`
- `chapters/ch05/01_scores_and_groups.py`
- `chapters/ch05/02_paper_journal.py`
- `chapters/ch05/03_guard_checks.py`
- `chapters/ch06/01_parity_at_depth.py`
- `chapters/ch06/strategy_01_A1_binary_parity.py`
- `chapters/ch06/strategy_02_A2_negrisk_bundles.py`
- `chapters/ch07/01_nested_contracts.py`
- `chapters/ch07/strategy_03_A3_logical_arbitrage.py`
- `chapters/ch07/strategy_04_A4_date_ladder.py`
- `chapters/ch07/strategy_05_A5_cross_venue.py`
- `chapters/ch07/strategy_06_A6_legged_accumulation.py`
- `chapters/ch08/01_favorite_carry.py`
- `chapters/ch08/README.md`
- `chapters/ch08/strategy_07_C8_favorite_carry.py`
- `chapters/ch08/strategy_08_C9_holding_rewards.py`
- `chapters/ch08/strategy_09_C4_tail_ladder.py`
- `chapters/ch09/01_model_vs_market.py`
- `chapters/ch09/README.md`
- `chapters/ch09/strategy_10_C1_model_value.py`
- `chapters/ch09/strategy_11_C3_weather_ensemble.py`
- `chapters/ch09/strategy_12_C2_llm_forecasts.py`
- `chapters/ch10/01_crypto_probabilities.py`
- `chapters/ch10/strategy_13_C5_options_value.py`
- `chapters/ch10/strategy_14_C6_twap_pricing.py`
- `chapters/ch11/01_reaction_and_fade.py`
- `chapters/ch11/strategy_15_B1_news_catalysts.py`
- `chapters/ch11/strategy_16_B2_overreaction_fade.py`
- `chapters/ch11/strategy_17_B3_macro_calendar.py`
- `chapters/ch11/strategy_18_B4_attention_rotation.py`
- `chapters/ch12/01_base_rate_interval.py`
- `chapters/ch12/README.md`
- `chapters/ch12/strategy_19_B5_mention_markets.py`
- `chapters/ch12/strategy_20_B6_count_buckets.py`
- `chapters/ch12/strategy_21_C10_launch_fdv.py`
- `chapters/ch13/01_latency_budget.py`
- `chapters/ch13/strategy_22_D1_crypto_latency.py`
- `chapters/ch13/strategy_23_D2_sports_latency.py`
- `chapters/ch13/strategy_24_D3_oscillation_scalping.py`
- `chapters/ch14/01_resolution_watch.py`
- `chapters/ch14/strategy_25_B7_resolution_rules.py`
- `chapters/ch14/strategy_26_B8_dispute_windows.py`
- `chapters/ch15/01_reward_score.py`
- `chapters/ch15/strategy_27_E1_inventory_quotes.py`
- `chapters/ch15/strategy_28_E2_liquidity_rewards.py`
- `chapters/ch15/strategy_29_E3_sportsbook_quotes.py`
- `chapters/ch16/01_wallet_audit.py`
- `chapters/ch16/strategy_30_F1_whale_copying.py`
- `chapters/ch16/strategy_31_F2_wallet_flow.py`
- `chapters/ch17/01_hedge_payoffs.py`
- `chapters/ch17/strategy_32_G1_domain_expertise.py`
- `chapters/ch17/strategy_33_G2_polling.py`
- `chapters/ch17/strategy_34_G3_public_information.py`
- `chapters/ch17/strategy_35_H2_exposure_hedge.py`
- `chapters/ch18/01_martingale_exposure.py`
- `chapters/ch19/01_test_plan.py`
- `examples/strategy-inputs.md`
- `pyproject.toml`
- `src/polymarket_strategies/__init__.py`
- `src/polymarket_strategies/__main__.py`
- `src/polymarket_strategies/account_setup.py`
- `src/polymarket_strategies/baskets.py`
- `src/polymarket_strategies/carry.py`
- `src/polymarket_strategies/constraint_scan.py`
- `src/polymarket_strategies/crypto_pricing.py`
- `src/polymarket_strategies/data.py`
- `src/polymarket_strategies/edge_check.py`
- `src/polymarket_strategies/execution.py`
- `src/polymarket_strategies/fees.py`
- `src/polymarket_strategies/journal.py`
- `src/polymarket_strategies/jsonfile.py`
- `src/polymarket_strategies/negrisk_scan.py`
- `src/polymarket_strategies/order_store.py`
- `src/polymarket_strategies/parity_scan.py`
- `src/polymarket_strategies/reaction.py`
- `src/polymarket_strategies/resolution_watch.py`
- `src/polymarket_strategies/reward_score.py`
- `src/polymarket_strategies/safety.py`
- `src/polymarket_strategies/sizing.py`
- `src/polymarket_strategies/strategies.py`
- `src/polymarket_strategies/strategy_baskets.py`
- `src/polymarket_strategies/strategy_catalog.py`
- `src/polymarket_strategies/strategy_cli.py`
- `src/polymarket_strategies/strategy_models.py`
- `src/polymarket_strategies/strategy_signals.py`
- `src/polymarket_strategies/trade_plan.py`
- `src/polymarket_strategies/trading_cli.py`
- `src/polymarket_strategies/wallet_audit.py`
- `templates/paper-journal.csv`
- `tests/conftest.py`
- `tests/helpers.py`
- `tests/test_account_setup.py`
- `tests/test_audit_regressions.py`
- `tests/test_calculators.py`
- `tests/test_execution.py`
- `tests/test_indexed_workflows.py`
- `tests/test_reader_exercises.py`
- `tests/test_resolution_watch.py`
- `tests/test_scanners.py`
- `tests/test_strategies.py`
- `tests/test_strategy_baskets.py`
- `tests/test_strategy_catalog.py`
- `tests/test_strategy_cli.py`
- `tests/test_strategy_models.py`
- `tests/test_strategy_signals.py`
- `tests/test_trade_plan.py`
- `tests/test_trading_cli.py`
- `tests/test_trading_workflows.py`
- `tests/test_wallet_audit_run.py`
- `uv.lock`
