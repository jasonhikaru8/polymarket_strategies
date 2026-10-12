# Changes in 0.5.0

Version 0.5.0 (9 October 2026) makes the trading toolkit easier to set up and use. The order checks, the fee model, the ledger and the calculations did not change; the 1265 offline tests (50 new) pass.

The release was rebuilt on 12 October 2026 with documentation and help-text fixes only: the README says how to get the code, `pyproject.toml` names the author and the repository, TRADING.md says that only an order expiry less than five minutes away gets a fresh window when you type `APPROVE` and that `trade check` also asks the geoblock endpoint, the help screens show the full command name, and `.gitignore` also covers `.DS_Store`, `dist/` and `build/`. No check, calculation or order behavior changed; the 1265 tests pass with Python 3.13 and with Python 3.11.

- **`trade setup`** asks, once, for the five account values (the four secrets are hidden) and offers to save them in `credentials.env` in the per-user folder, readable only by you. The file is not encrypted; the README and TRADING.md say so. Every account command (`submit`, `status`, `cancel`, `recover`, `resolve`, `check`) now reads it automatically. A value in the environment still wins, and `--prompt-credentials` still works. The file is refused if other users can read it, if it is a link, or if a line is not one of the five names; no value is ever printed.
- **`trade check`** reports what is ready and what is missing without showing any value: the five values, whether the wallet is the signer's own address or a smart wallet, the `KILL` files, the location check and, by logging in read-only, the pUSD balance and which exchange contracts may spend it. It exits nonzero if the account is not ready. `--offline` limits it to local facts.
- **`trade approve FILE`** replaces editing the approval by hand. It prints the market's current public rules, source and deadline, asks what exactly must happen for YES, why the market fits the strategy and (only if the rules name none) which source decides, and then needs a typed `APPROVE`. It works only in your own terminal and has no `--yes`. The approval starts when you type `APPROVE`, not when you began reading. It lasts 60 minutes unless `--minutes` says otherwise (10 to 1440) and never outlasts the market or the forecast; an order expiry less than five minutes away is moved to a fresh eleven-minute window from that moment, and an order never outlasts its approval. For a config from `strategy prepare`, pressing Enter keeps the strategy's own YES definition. All 15 forecast methods are tested from `strategy prepare` through `approve` to an eligible preview.
- **`trade inspect` takes the order on the command line:** `--outcome`, `--side`, `--shares`, `--price` and `--max-cash` (`--shares` also sets the share limit). Without them the draft is unchanged, with every limit at zero.
- **A risk notice** (the author is not responsible for any investment loss; use at your own risk) is at the top of the README, TRADING.md and STRATEGIES.md, and `trade setup` and `trade submit` print it.
- **Docs.** The README's trading section is now a short setup-to-submit walkthrough. TRADING.md describes the quick path, the three ways to supply credentials and `trade check`. It also says what the SDK's `setup_trading_approvals()` grants (an unlimited pUSD allowance to each exchange contract and permission to move all positions) and how to revoke it.

# Changes in 0.4.4

Version 0.4.4 (7 October 2026) follows a third outside review of the book. Nothing in the trading path or the calculations changed; the 1215 offline tests (one new) pass.

- **The journal's evidence screen waits for the whole sample.** `journal.summarize` no longer sets `evidence_gate_met` while any logged group is pending, and it adds a `pending_warning`. The groups that resolve first can differ from the sample fixed in advance (a "by" market's YES can settle early while NO waits for the deadline): in the new test, 300 of 400 groups at 80 cents have resolved with 15 losses, so the resolved groups average +$0.15 with an interval above zero, yet if the 100 pending groups lose, the whole sample averages −$0.0875. Groups that have resolved are still summarized, and the counts and interval are unchanged.
- **`min_edge` and cash.** STRATEGIES.md says that for a position held to a distant resolution, `min_edge` should include the cash the price could earn meanwhile.

# Changes in 0.4.3

Version 0.4.3 (7 October 2026) follows a consistency check of the package against the book's text. Nothing in the trading path or the calculations changed; the 1214 offline tests (two new output pins) pass.

- **The manifest lists the journal template.** `templates/paper-journal.csv` (shipped since 0.4.1, the two starting lines of the book's Appendix D) is now in `RELEASE_MANIFEST.md` and named in `README.md`, which also says that the journal module refuses a row with no shares, so unfilled bids belong in the spreadsheet or in a plain-text list.
- **README names the repository.** The package is distributed only from `github.com/jasonhikaru8/polymarket_strategies` and is on no package index; the README now says so, as the book does.
- **Chapter 11 and 13 exercises print rounded numbers.** `chapters/ch11/01_reaction_and_fade.py` prints `0.3333` and `0.08` instead of `0.33333333333333326` and `0.07999999999999996`, and `chapters/ch13/01_latency_budget.py` prints `0.012` instead of `0.011999999999999908`; the offline tests now pin both.
- **`strategy example N --out FILE` says plainly when FILE exists.** It still never overwrites; the message is now "FILE already exists; choose a new name" instead of the raw `[Errno 17]` text.

# Changes in 0.4.2

Version 0.4.2 (5 October 2026) prepares the package for Polymarket's Protocol V2, following Polymarket's own migration guides (read 5 October 2026).

- **Outcome IDs follow the market's `version`.** In a V2 market an outcome is priced and ordered by its position ID, in a V1 market by its CTF token ID, and a live V1 market can carry both fields. `parity-scan`, `negrisk-scan`, `constraint-scan` and `trade inspect` now choose by `version` and refuse a market whose version is missing or unknown, whose ID is missing, or whose ID lies in the other protocol's number range (`outcome_asset_id` in `data.py`). For V1 markets nothing changes, including the plan fingerprint.
- **`polymarket-client` 0.12.0** (was 0.11.0), the release the V2 guides name. All offline tests pass on it.
- **`resolution-watch --disputed` is V1 only**, and the README says so: it filters on the UMA status, which a V2 market does not report.
- **TRADING.md** says that V2 markets need their own approvals (ExchangeV3).
- **Not verified:** no V2 market existed on 5 October 2026, so nothing was run against one. Re-check after V2 starts.

# Changes in 0.4.1

Version 0.4.1 (5 October 2026) follows the book's review of 5 October 2026.

- **Strategy 13 (C5) asks what the market pays on.** A new required field, `payoff_type`, is `finish_above`, `touch` or `range`. A call spread prices finishing above a level, so a touch ("hit $X") market is refused unless you supply your own `touch_probability` and `touch_conversion_notes` (for example from `crypto_pricing.touch_probability`); on Chapter 10's December rung the finish-above number would have shown a NO edge of +1.84 cents where the chapter's touch model gives +0.36. A range subtracts a second call spread at its upper level (`upper_call_low_cost`, `upper_call_high_cost`, `upper_strike_width`). `option_contract_match_reviewed` now covers the payoff type and observation window, and the output names `payoff_type` and `payoff_reference`. Inputs written for 0.4.0 need the new field.
- **Strategy 20 (B6)'s example stresses wider spreads.** It keeps Chapter 12's multiplier of 6 and stresses multipliers of 6, 16 and 24 (was 4 and 8 around the 6), since the book's weekly count data imply about 16 to 22; STRATEGIES.md says how to choose one. A pace or multiplier listed twice now counts as one stress scenario.
- **`strategy analyze` flags leftover placeholder text.** An input that still contains the example's `example.invalid` or `SYNTHETIC` text, with the `demo` marker removed, is now `eligible: false` with the reason given first and `synthetic: true`, as `strategy prepare` already refused it. A marked demonstration is unchanged.
- **Disputes are counted once each.** Some markets list every oracle status twice, so `resolution-watch --disputed` collapses consecutive repeats before counting: `["proposed", "proposed", "disputed", "disputed"]` is one dispute, not a token vote.
- **Network errors end in one line.** `parity-scan`, `negrisk-scan`, `constraint-scan`, `resolution-watch`, `wallet-audit`, `calc --slug` and `trade inspect`, `preview` and `watch` print one plain line and exit with status 1 when Polymarket's public data cannot be reached, instead of a Python traceback; a read-only `trade` lookup no longer mentions the ledger. `wallet-audit` checks that the address is `0x` and 40 hexadecimal characters before it sends anything.
- **Docs and exercises.** STRATEGIES.md and the Chapter 8, 9 and 12 READMEs use `strategy example N --out FILE` instead of `>`; STRATEGIES.md says plainly that Strategy 17 (B3) models a released figure's surprise against consensus (a pre-release market-versus-benchmark gap is a `calc` check), and that Strategy 19 (B5) computes a per-word base rate, not Chapter 12's simple-word NO lead. The Chapter 1 exercise prints rounded numbers (`'gross_edge': 0.02`, not `0.020000000000000018`).

# Changes in 0.4.0

Version 0.4.0 is the first version meant for readers. It changes the following.

## Fees and orders

- **BUY fees are cash on top of the price.** A taker BUY pays price x shares plus a fee of shares x rate x price x (1 - price) in pUSD, and receives every share. A SELL fee comes out of the proceeds. The trading preview, the basket and signal tools and the docs all use this, and the earlier "fee deducted from the shares" model is gone. Removed outputs: `estimated_received_shares`, `estimated_fee_shares`, `quantity_basis`; renamed: `target_actual_cost_per_share`, `observed_share_flow`. Basket legs must say `fee_collection: "cash"`.
- **Uncertain submissions stay blocking.** A response such as `unmatched` (placed, but no order ID) or an unclassified failure is recorded as UNKNOWN. A refusal that proves nothing was placed (HTTP 4xx or 503, rate limit, an explicit refusal code) is REJECTED. `trade recover INTENT` finds the one matching open order without an order ID; `trade resolve INTENT --confirm` closes an intent whose order expired with no order or fill.
- **One ledger and one `KILL` file per user** (`~/.polymarket-strategies/`, or the absolute folder in `POLYMARKET_STRATEGIES_HOME`; a relative value is refused), whatever folder a command runs from. A ledger path that is a folder or a link is refused.
- **A typed `YES` before submitting** (or `--yes` for a reviewed order); for a SELL the prompt says how many shares are sold, not "0 pUSD at risk", and `--live` is checked before anything is asked. Only markets whose outcomes are labeled Yes and No are accepted. A deadline without a time zone is read as UTC.
- **The location check and the smart-wallet check now work.** Polymarket's geoblock endpoint and the public Polygon RPC node answer HTTP 403 to Python's default identification, so every live submit would have failed closed; both requests now name `polymarket-strategies`. A mistyped `--ledger` no longer creates an empty ledger when you only read it, and an order the exchange accepted is reported by its ID even if the local ledger is down.
- `status --count N` keeps polling after a failed check. Credential-looking keys in strategy inputs (`signer_key`, `keystore`, `bearer`, `authorization`, `recovery phrase` and the like) are refused however they are spelled; a harmless key such as `polymarket_slug` is not.

## Strategy tools

- `strategy prepare` keeps the stricter of `--min-edge` and the `min_edge` in your inputs, runs the strategy's own screen first, carries the inputs' outcome, gives the order a fresh eleven-minute window (never past the forecast's `valid_until` or your approval) and refuses inputs that still contain the example's placeholder text. Inputs nested more than 60 levels deep, or holding integers too large for a number, are reported as input problems. `strategy example N --out FILE` writes UTF-8; input files saved as UTF-16 or with a byte-order mark are read.
- Strategy 19 accepts all-same histories (0 of n, n of n); the Wilson interval stays inside 0 to 1. Strategy 14 applies a screen. Strategy 26 (and Strategy 33 without an election-winning forecast) reports `eligible: null`. Strategy 32 needs `min_decisions` and a record better than always saying 50%. Strategy 11 buckets are half-open [lower, upper). Strategy 20 uses a negative-binomial count model and prints the bell curve as `normal_approximation_probability`. Annual rates must be fractions of at most 1. Strategies 4 and 21 no longer require identical legs definitions; Strategies 30 and 31 check cash against size x price.

## Calculators and public tools

- `calc` names the fee schedule it used, takes `--category` from a fixed list, requires `--days` of at least 1 and prints rounded numbers. Sizing and carry functions refuse impossible inputs. `touch_probability` and `implied_touch_vol` take `direction="down"` for a dip market.
- `wallet-audit` asks for taker fills and the full trade history explicitly and says so (`scope`, `pnl_basis`); `independent_decisions` is now `distinct_events`. `parity-scan` and `negrisk-scan` read one page of 100, accept `--limit` from 1 to 100 and print what they read and skipped. `resolution-watch` reports unknown slugs and looks up more than 100 slugs in batches. `journal-summary` takes `--strategy`, skips blank lines and reports orphan outcome lines. `polymarket-strategies --help` and `--version` work.
- Chapter exercises 2, 5 (journal), 6, 7, 10 and 19 now print the numbers of their chapters, and a test pins them.
