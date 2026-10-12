# Reader code for *35 Polymarket Strategies, Graded by Evidence*

All 35 indexed strategy tools, chapter exercises, public scanners, a paper journal and a reader-controlled trading toolkit, written by Jason Hikaru for the book.

> **Risk notice.** Trading prediction markets can lose all the money you put in. This software and the book are provided as is, with no warranty. The author is not responsible for any investment loss or other damage from using them; you use them entirely at your own risk. Nothing here is investment, legal or tax advice. Start with an amount you can afford to lose, read the code before you enable trading, and keep your keys private.

The package is distributed only from its repository, `github.com/jasonhikaru8/polymarket_strategies`; it is not on PyPI or any other package index, so do not install anything of this name from elsewhere. The book describes version 0.5.0; `CHANGES.md` lists what each version changed.

The exercises use made-up inputs unless the script explicitly reads a live endpoint. They illustrate the method; they do not reproduce all of the book's research results. The author's figure-generation scripts, study collectors, frozen raw snapshots and publication tools are excluded.

## Start

Requires Python 3.11 or later and [uv](https://docs.astral.sh/uv/) 0.12.15 or later (the lock file and the build backend need it). Get the code with `git clone https://github.com/jasonhikaru8/polymarket_strategies.git` (or **Code > Download ZIP** on that page), then open a terminal in its folder:

```bash
uv sync
uv run pytest
uv run python chapters/ch03/01_fees_and_break_even.py
uv run polymarket-strategies calc --rate 0.04 --price 0.95 --shares 100 --days 30 --prob 0.97
```

The calculator prints the fee schedule it used, a $0.19 fee and a break-even probability of 0.9519: a BUY fee is paid in pUSD on top of the price. Without `--category`, `--rate` or `--slug` it uses the politics category, and says so. The category defaults are a September 2026 reference table. For current orders, the trading preview screens your forecast against the all-in cost per share (price plus fee). `calc --slug MARKET_SLUG` reads the market's own public fee schedule; inspect its exponent and eligibility too.

The arithmetic uses the Python standard library. The official `polymarket-client` SDK supplies market access, signing and order APIs. Version 0.12.0 is pinned (the first release Polymarket's Protocol V2 guides name); `uv.lock` records the tested dependency versions. Exercises, scanners, inspection and previews require no credentials. Only the explicit trading commands connect your account or submit/cancel an order.

## All 35 strategies, in book order

Open [STRATEGIES.md](STRATEGIES.md) for the full index, inputs and execution scope. Every strategy has a chapter entry file such as `strategy_07_C8_favorite_carry.py` or `strategy_19_B5_mention_markets.py`. Each runs a synthetic demonstration, emits a complete editable JSON schema with `--example`, and analyzes your own documented data with `--inputs FILE`.

```bash
uv run polymarket-strategies strategy list
uv run polymarket-strategies strategy example 10
uv run python chapters/ch09/strategy_10_C1_model_value.py
```

Fifteen indexed forecast methods connect to explicitly reviewed single-outcome orders. Twenty methods supply basket/timing/exit analysis, quote proposals, reward calculations, monitoring or scenario hedges. They are labeled analysis-only and cannot create an executable strategy plan. This package requires reader-supplied evidence; it does not operate 35 unattended bots or automatically collect every strategy's external data.

## Trade with your own account

**Before you start,** you need a funded Polymarket wallet (pUSD), the exchange approvals for it, and the CLOB API key, secret and passphrase. Polymarket's [wallet and authentication guide](https://docs.polymarket.com/trading/wallets-auth) explains how to get them. This toolkit does not create or fund a wallet, or grant approvals for you.

Once, to enter your account values and check that everything is ready:

```bash
uv run polymarket-strategies trade setup     # asks for the five values (the four secrets are hidden); offers to save them privately
uv run polymarket-strategies trade check     # location, pUSD balance, allowance: what is missing, if anything
```

For each order:

```bash
# 1. Draft the order. This reads the public market and changes nothing.
uv run polymarket-strategies trade inspect MARKET_SLUG --outcome YES --shares 5 --price 0.40 --max-cash 3 --out trade.json
# 2. Read the current rules in your terminal and approve them (nothing to edit by hand).
uv run polymarket-strategies trade approve trade.json
# 3. Preview against the live book. Look for "eligible": true and copy the plan_id.
uv run polymarket-strategies trade preview trade.json
# 4. Send it. Both switches are needed, and you must type YES in your terminal.
export POLYMARKET_STRATEGIES_LIVE=1
uv run polymarket-strategies trade submit trade.json --confirm PLAN_ID --live
# 5. Follow it. INTENT_UUID is the "intent_id" inside trade.json.
uv run polymarket-strategies trade status INTENT_UUID
uv run polymarket-strategies trade cancel INTENT_UUID --confirm
```

**Your account values.** `setup` asks for `POLYMARKET_WALLET_ADDRESS` (public), `POLYMARKET_SIGNER_PRIVATE_KEY`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET` and `POLYMARKET_API_PASSPHRASE`. If you agree, it saves them in `credentials.env` inside `~/.polymarket-strategies/`, and every account command then finds them. On a Mac or Linux the toolkit refuses the file unless only you can read it; on Windows it cannot check file permissions, so keep the file in your own profile folder. **That file is not encrypted: your signing key sits on your disk.** Use a dedicated wallet that holds only money you can afford to lose, and never copy the file into a project folder, an email or GitHub. If you prefer not to save anything, put the five values in your own environment or credential manager, or add `--prompt-credentials` to an account command, which asks for whatever is still missing and keeps it only for that command. A value in your environment always wins over the saved file.

**To trade one of the strategies,** start from its input file and let the toolkit build the order, then approve it the same way:

```bash
uv run polymarket-strategies trade inspect MARKET_SLUG --outcome YES --shares 5 --price 0.40 --max-cash 3 --out inspected.json
uv run polymarket-strategies strategy prepare 10 forecast.json inspected.json --out trade.json
uv run polymarket-strategies trade approve trade.json    # Enter keeps the strategy's own YES definition
uv run polymarket-strategies trade preview trade.json
```

Fifteen of the 35 strategies can create an order this way; [STRATEGIES.md](STRATEGIES.md) says which, and what each needs. Then `submit` as in step 4.

**What stays in your hands.** The toolkit never approves an order for you: `approve` and `submit` work only in your own terminal, `submit` needs the exact `plan_id`, `--live`, `POLYMARKET_STRATEGIES_LIVE=1`, no `KILL` file and a location Polymarket allows, and it submits one bounded, expiring limit order at a time. You supply every probability yourself. Public quote watching (`preview`, `watch`) never submits or changes anything. [TRADING.md](TRADING.md) explains every field, partial fills, cancellation and recovery after an uncertain submission.

The original three workflows remain available, alongside the indexed forecast methods:

| Book strategy | Decision input | Worked exercise |
| --- | --- | --- |
| C1: Model-based value betting | Your independent, dated probability forecast and conservative bounds | `chapters/ch09/strategy_10_C1_model_value.py` |
| C8: Favorite carry | Your forecast plus minimum favorite price, conservative expected return and holding horizon | `chapters/ch08/strategy_07_C8_favorite_carry.py` |
| B5: Mention markets | Your reviewed comparable historical events; the code calculates a base rate and Wilson bounds | `chapters/ch12/strategy_19_B5_mention_markets.py` |

Chapter entry files are offline demonstrations and analyses. The supported forecast methods connect through `strategy prepare` and `trade` using your reviewed config and account. [STRATEGIES.md](STRATEGIES.md) explains that workflow; [strategy-inputs.md](examples/strategy-inputs.md) documents the original three schemas. These tools do not establish forecast accuracy or profitability.

## Chapters and sections

Run a script from this folder with `uv run python` followed by its path. Change only the made-up inputs you understand. Chapter 14 needs the network and either market slug(s) you supply or the `--disputed` list; all other scripts below run offline. Their chapter numbers refer to the book, and the filename's first number orders the exercises within that chapter.

| Chapter | Section exercise | Path |
| --- | --- | --- |
| 1 | Edge after spread and fees | `chapters/ch01/01_edge_after_costs.py` |
| 2 | Split a complete YES/NO set | `chapters/ch02/01_complete_set.py` |
| 3 | Fees and break-even | `chapters/ch03/01_fees_and_break_even.py` |
| 4 | Fractional Kelly and related exposures | `chapters/ch04/01_fractional_kelly.py` |
| 5 | Model scores and grouped results | `chapters/ch05/01_scores_and_groups.py` |
| 5 / Appendix D | Paper journal demonstration | `chapters/ch05/02_paper_journal.py` |
| 5 / Appendix G | Guard checks without live orders | `chapters/ch05/03_guard_checks.py` |
| 6 | Walk a pair of books at depth | `chapters/ch06/01_parity_at_depth.py` |
| 7 | Logically nested contracts | `chapters/ch07/01_nested_contracts.py` |
| 8 | High-price carry and loss exposure | `chapters/ch08/01_favorite_carry.py` |
| 9 | Fit a blend, then test later events | `chapters/ch09/01_model_vs_market.py` |
| 10 | Terminal, touch and average rules | `chapters/ch10/01_crypto_probabilities.py` |
| 11 | Reaction speed and fading a rumor | `chapters/ch11/01_reaction_and_fade.py` |
| 12 | Base-rate interval | `chapters/ch12/01_base_rate_interval.py` |
| 13 | Latency and cost budget | `chapters/ch13/01_latency_budget.py` |
| 14 | Public resolution metadata | `chapters/ch14/01_resolution_watch.py` |
| 15 | Liquidity-reward score | `chapters/ch15/01_reward_score.py` |
| 16 | Synthetic wallet audit | `chapters/ch16/01_wallet_audit.py` |
| 17 | Hedge cash flows | `chapters/ch17/01_hedge_payoffs.py` |
| 18 | Martingale exposure | `chapters/ch18/01_martingale_exposure.py` |
| 19 | Paper-test pace and exposure budget | `chapters/ch19/01_test_plan.py` |

## Read-only commands

```bash
uv run polymarket-strategies parity-scan --limit 20
uv run polymarket-strategies negrisk-scan --limit 20
uv run polymarket-strategies constraint-scan YOUR_CONSTRAINTS.json
uv run polymarket-strategies wallet-audit YOUR_PUBLIC_ADDRESS --limit 1000
uv run polymarket-strategies resolution-watch YOUR_MARKET_SLUG
uv run polymarket-strategies resolution-watch --disputed
uv run polymarket-strategies journal-summary YOUR_JOURNAL.jsonl
```

All but `journal-summary` read live public endpoints; if Polymarket cannot be reached, they stop with one plain error line and exit status 1 (as do `calc --slug` and `trade inspect`, `preview` and `watch`). Replace the uppercase placeholders; they are not real slugs or addresses. `wallet-audit` refuses anything but `0x` followed by 40 hexadecimal characters before it sends a request. A constraints file is a JSON list such as `[{"smaller": "your-smaller-slug", "larger": "your-larger-slug"}]`. You must establish the implication under both contracts' rules. A gap in a scan is a calculation at displayed depth, not a guarantee that both legs fill, or a complete transaction-cost estimate.

`parity-scan` and `negrisk-scan` read one page of the 100 open markets (or events) with the most 24-hour volume, keep the tradable ones and scan the first `--limit` of them (1 to 100). Each prints, on its error stream, how many it read and why others were skipped, so a result always says which markets it covers. `constraint-scan` reads your slugs in batches of 100 and reports a slug it cannot find as an error row. `resolution-watch` gives an error row for a slug that matches no market; `--disputed` lists at most 100 markets and says so when the list may be longer, and counts each dispute once even when a market's status history lists every step twice. `--disputed` filters on the oracle (UMA) status that Gamma reports for V1 markets, so it cannot list a Protocol V2 market, which reports `resolutionStatus` instead; for a V2 market, name its slug and read the Data API `status` in the output (use a payout only when the status is `resolved`).

**Protocol V1 and V2 markets.** Polymarket is moving new markets to Protocol V2 (tentatively from 2 November 2026). A market's `version` decides which ID an outcome is priced and ordered by: its CTF token ID in a V1 market, its position ID in a V2 market (a live V1 market can carry both fields). The scanners and `trade inspect` choose by `version`, and refuse a market whose version is missing or whose ID does not belong to that version. Nothing here has been run against a live V2 market, because none existed on 5 October 2026; re-check after V2 starts.

`wallet-audit` counts distinct events among a wallet's taker buys (fills where the wallet took liquidity, not fills of its resting orders), and reads open and closed positions, with a configurable limit. It reports truncation, and every result carries its own `scope` and `pnl_basis` lines: profit figures are realized plus unrealized, with open positions marked to the current price. Its summary does not establish a wallet owner's identity, misconduct, or copyable performance. The included wallet exercise is synthetic; this package ships no real-wallet dumps.

The journal records decisions before the result and appends outcomes later. It groups linked bets and keeps incomplete groups out of the analyzed sample. Keep one journal per test: decisions of different strategies in one file are pooled into one interval unless you pass `--strategy NAME`, and the summary lists the strategies it found and any outcome lines that match no decision. Profit is in dollars per decision (all the linked bets of a group added together), so mixed position sizes mix units. Its 100/300 counts are illustrative checkpoints, not universal sample requirements. An all-win sample does not pass the evidence screen. A positive interval is a numerical check, not approval to trade; missing tails, dependence, selection, costs and later unseen events still matter. The journal module models held-to-resolution payouts; use the spreadsheet protocol for early exits rather than recording an exit as a settlement. `templates/paper-journal.csv` holds the spreadsheet's header row and one filled-in row (the book's Appendix D); the journal module refuses a row with no shares, so keep unfilled bids in the spreadsheet or in a plain-text list beside the journal.

## Scope and checks

The table above covers general chapter exercises. The [35-strategy index](STRATEGIES.md#find-your-strategy) supplies every strategy-specific filename. `src/polymarket_strategies/` contains their shared calculations, evidence checks, public readers and trading implementation. Short chapter files call those modules; the complete folder is necessary. `tests/` covers calculations, contract/quote checks and simulated authenticated order lifecycles. Tests do not establish forecast accuracy, eligibility or economic edge. Neither the full research data nor its plotting pipeline is included.

Read the code before enabling trading. Your signing key and API credentials stay on your computer (in your environment or in the private `credentials.env` that `trade setup` can create); do not send them to the author or put them in GitHub, example configs or logs. New orders require the preview confirmation, a typed `YES` in your terminal, `--live`, `POLYMARKET_STRATEGIES_LIVE=1`, no `KILL` file (in `~/.polymarket-strategies/` or the current folder) and an explicitly permitted geoblock response. The order ledger is one file per user in the same folder. Cancellation remains available when new orders are stopped. The toolkit does not deploy wallets, grant token approvals or bypass restrictions. Its guard protects its own submission path; it cannot secure unrelated software.

MIT license applies to this selected software package. See [LICENSE](LICENSE). It does not license the book's text, tables or figures, or third-party data (code printed in the book that comes from this package is covered).
