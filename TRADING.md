# Reader-controlled trading

> **Risk notice.** Trading prediction markets can lose all the money you put in. This software and the book are provided as is, with no warranty. The author is not responsible for any investment loss or other damage from using them; you use them entirely at your own risk. Nothing here is investment, legal or tax advice. Start with an amount you can afford to lose.

This toolkit connects a reviewed market and strategy decision to a real limit order on your own account. It supports ordinary binary YES/NO markets, supported taker-only fee schedules and one outcome per order. All 35 strategies have indexed decision tools; fifteen forecast methods can feed this execution workflow. [STRATEGIES.md](STRATEGIES.md) lists every filename, schema and scope. Basket execution, continuous market making, wallet copying, redemption and unattended bots are outside this adapter.

Use the entire `reader-code/` package. Chapter scripts demonstrate the decision calculation; `trade` runs the shared contract, quote and execution workflow. Installation and the chapter index are in [README.md](README.md).

## 1. Understand the probability input

Run the synthetic examples without an account:

```bash
uv run python chapters/ch09/strategy_10_C1_model_value.py
uv run python chapters/ch08/strategy_07_C8_favorite_carry.py
uv run python chapters/ch12/strategy_19_B5_mention_markets.py
```

They print a decision, its assumptions and any rejection reasons. Their numbers are made up. A positive screen is not evidence of a profitable strategy.

- **C1 (`model_value`)**: provide an independent probability estimate, lower/upper conservative YES bounds, when it was produced and when it expires. The tool uses the lower bound for YES and one minus the upper bound for NO. It compares that conservative probability with the limit price and a fee reserve.
- **C8 (`favorite_carry`)**: provide the same forecast plus your minimum favorite price, maximum holding horizon and minimum conservative expected annual return. The return screen scales expected net return by time; it assumes no compounding and cannot predict settlement delays.
- **B5 (`mention_base_rate`)**: provide comparable historical binary events. The code estimates the YES frequency and Wilson bounds. Each observation needs a distinct event/group, known prior resolution, matching source/definition and a reviewed cohort. The interval reflects sampling uncertainty; it cannot fix a bad cohort or an unrepresentative future event.

For indexed methods, emit a complete input schema with `strategy example NUMBER`, replace its synthetic evidence and use `strategy prepare` as explained in [STRATEGIES.md](STRATEGIES.md#prepare-a-supported-strategy-order). The original `model_value`, `favorite_carry` and `mention_base_rate` schemas remain supported and are documented in [strategy-inputs.md](examples/strategy-inputs.md). External forecasts and historical events must be supplied/reviewed by the reader. Keep forecast evaluation on separate later events; Chapter 9's scoring tools can help.

`manual` permits a reader-selected trade without estimating probability. Its `min_edge` must be zero; the output deliberately reports no forecast or edge. Strategy workflows open BUY positions; a reviewed manual SELL can close an existing holding.

## 2. Inspect and approve a contract

Replace `MARKET_SLUG` with the slug from the market URL:

```bash
uv run polymarket-strategies trade inspect MARKET_SLUG --strategy model_value --out trade-local.json
```

Inspection prints the full public rules, source, deadline, YES/NO outcome IDs (token IDs in a V1 market, position IDs in a V2 market, chosen by the market's `version`) and a fingerprint. It creates an **unapproved** local config with zero cash/share limits. It refuses to overwrite an existing file.

**Quick path (no JSON editing).** Give the order on the command line, then approve the rules in your terminal:

```bash
uv run polymarket-strategies trade inspect MARKET_SLUG --outcome YES --shares 5 --price 0.40 --max-cash 3 --out trade-local.json
uv run polymarket-strategies trade approve trade-local.json
```

`--outcome` is `YES` or `NO`, `--side` is `BUY` (the default) or `SELL`, `--shares` sets the order size and the share limit, `--price` the limit price and `--max-cash` the most pUSD the order may cost, fee reserve included. `approve` prints the market's current public rules, source and deadline, then asks what exactly must happen for YES, which source decides (only when the rules name none) and why the market fits your strategy, and finally asks you to type `APPROVE`. For a strategy config from `strategy prepare`, Enter keeps the strategy's own YES definition. The approval starts when you type `APPROVE`, not when you began reading. It lasts 60 minutes unless you pass `--minutes` (10 to 1440), and never outlasts the market or the forecast. An order expiry less than five minutes away is moved to a fresh eleven-minute window from that moment, and an order never outlasts its approval. If you type anything else, nothing changes. `approve` works only in your own terminal and has no `--yes`.

To do the same by hand, open `trade-local.json` in your editor:

1. Read the full rules and any additional context on Polymarket. Check the named source, exact cutoff/time zone, threshold, tie treatment and exceptional outcomes. Public fingerprint matching is a change detector, not a legal or semantic interpretation of every rule. It does not independently monitor onchain clarifications.
2. Write the exact target event in `approval.yes_definition` and the source in `approval.resolution_source`. If the public source field is empty, identify it from the rules yourself. Explain the strategy match in `approval.note`.
3. Set the desired `outcome`, `side`, `shares`, `limit_price`, `post_only` and `expires_at`. Monetary quantities are decimal strings. Shares must meet the current market minimum and have at most two decimal places.
4. Choose `limits.max_cash`, `limits.max_shares` and the maximum permitted book age. The cash screen includes a conservative modeled fee reserve. The limit price and quantity bound principal and shares; fees are applied by the platform at match time, and rounding or changing fees can differ from the reserve. These are per-order screens, not portfolio or daily-loss controls.
5. Fill in the strategy's inputs. Its YES definition and source must exactly match your approval fields.
6. Set `approval.approved` to `true` only after the review. Keep `reviewed_at`/`valid_until` current. Approval lasts at most 24 hours; every order must expire before its approval, forecast and contract deadline.

A new config's default `expires_at` is eleven minutes after `inspect`. `strategy prepare` gives an older file a fresh eleven-minute window, but the forecast and approval must still have at least three minutes left, so `inspect` again if `prepare` says the window is too short.

The config's `intent_id` identifies one attempted order. Preserve it for status, cancellation and recovery. To make a later, deliberately separate order, prepare a new inspected config with a new ID and repeat the review. Do not change an ID to bypass an uncertain submission.

Times in configs are Unix seconds. You can calculate them locally without secrets:

```bash
uv run python -c 'import time; n=int(time.time()); print("now:", n, "one hour:", n+3600)'
```

`expires_at` is the GTD timestamp. The platform expires GTD orders one minute before that timestamp and requires at least three minutes of lead time; this toolkit adds five seconds of buffer. A forecast/approval with less remaining validity cannot support a new order. Re-inspect and review if the fingerprint changes. [GTD documentation](https://docs.polymarket.com/trading/place-orders)

## 3. Preview and watch changing quotes

```bash
uv run polymarket-strategies trade preview trade-local.json
uv run polymarket-strategies trade watch trade-local.json --interval 5 --count 12
```

Neither command loads credentials, signs or submits an order. `watch` repeats public previews; it does not reprice or cancel anything.

Important output:

| Field | Meaning |
| --- | --- |
| `eligible` / `reasons` | Whether all current checks pass, or why the plan is rejected |
| `plan_id` | Confirmation for the exact config; changing a field changes this identifier |
| `contract_fingerprint` | Current public contract identity/rules mapping |
| `decision` | Probability source, conservative edge and assumptions; manual decisions have no estimate |
| `quote` | Current best prices, book timestamp, tick size, minimum quantity and displayed depth within your limit |
| `cash_bound`, `fee_bound` | Conservative modeled reservations, not actual cash/fee receipts |
| `fee_model` | How each fee is collected and the all-in fee per share used for the decision |
| `order` | Exact intended token, side, limit, quantity and expiration |

If the ask rises above your BUY limit, immediately available quantity can become zero. The tool keeps your limit; it never chases the higher quote. A non-post-only limit order may fill partly and leave a remainder resting. A post-only order currently crossing the book is rejected. Price/size restrictions, missing fees, stale data, resolution activity or changed rules stop submission.

A BUY fee is paid in pUSD on top of price × shares, and every matched share is delivered; a SELL fee comes out of the pUSD proceeds. The forecast screen compares your probability with the all-in cost per share (price plus fee). For fee-bearing BUYs this adapter accepts supported monotone curves (rate at most one, exponent one or two), so the limit price screens the worst modeled cost for better-price fills. It reserves a small rounding buffer; actual partial-fill rounding or changed fees can differ. `cash_bound` reserves the principal plus the largest fee the order could pay. [Fees](https://docs.polymarket.com/trading/fees)

## 4. Connect your existing account locally

You need an existing funded Polymarket wallet, its authorized signer and the CLOB API key/secret/passphrase. An API key is separate from the wallet signature that authorizes an order. The selected wallet must already have the exchange permissions needed to trade. Follow the official [wallet/authentication guide](https://docs.polymarket.com/trading/wallets-auth) to obtain credentials and set up your account.

This toolkit does not create a wallet, grant approvals, fund the account or recover missing allowances automatically. Protocol V2 markets settle through a different exchange contract (ExchangeV3), so a wallet that can trade V1 markets still needs its own V2 approvals (pUSD for buying; the positions contract for selling); the official SDK's `setup_trading_approvals()` grants them. Know what it grants: an unlimited pUSD allowance (the largest possible amount) to each exchange contract, and permission to move all of your positions. That is one more reason to trade from a dedicated wallet with a small balance. When you stop trading from the wallet, revoke them: set each pUSD allowance to zero and turn the positions permission off, with your wallet's own tools or a token-approval checker you trust. The allowance check below reads the allowance for the exchange that matches the order, and stops if it falls short. It checks deployment before authenticating a smart wallet and uses separate `create_limit_order` / `post_order` calls.

Set these environment variables locally:

```text
POLYMARKET_SIGNER_PRIVATE_KEY
POLYMARKET_WALLET_ADDRESS
POLYMARKET_API_KEY
POLYMARKET_API_SECRET
POLYMARKET_API_PASSPHRASE
```

Do not put actual values in terminal commands, the order config, the book, screenshots or GitHub. There are three ways to supply them, and an environment variable always wins over the others:

1. **Your own environment or credential manager** (the most careful choice).
2. **`--prompt-credentials`** on an account command. In your own terminal it asks for missing values, hides the four secret entries and keeps them only for that process. The wallet address is public and is shown normally. A noninteractive terminal or an inability to hide input causes rejection.
3. **`trade setup`**, once. It asks for whatever is missing (the wallet address is shown as you type; the four secrets are hidden), then offers to save the values in `credentials.env` in your per-user folder (`~/.polymarket-strategies/`, or the absolute folder named by `POLYMARKET_STRATEGIES_HOME`). That file is **not encrypted**: the signing key sits on your disk, readable only by your user account (mode 600). On a Mac or Linux the toolkit refuses a file that other users can read; on Windows it cannot check file permissions, so keep the file in your own profile folder. It also refuses a link, or a line that is not one of the five names. Every account command then finds the values by itself. The file lives outside any project folder, so it cannot be committed by accident; do not copy it into one. Use a dedicated wallet that holds only money you can afford to lose.

```bash
uv run polymarket-strategies trade setup
uv run polymarket-strategies trade check
```

`trade check` is the readiness test: it lists which of the five values are set (never their contents), whether the wallet is the signer's own address or a smart wallet, whether a `KILL` file exists, whether your location may place orders, and, by logging in read-only, your pUSD balance and which exchange contracts may spend it. It prints what is missing and exits nonzero if the account is not ready. `--offline` limits it to the local facts.

The prompt is an intentional local authentication step, so audit this code and its dependencies before entering a key. It does not send private signing keys to the author or to an API. Use a signer whose intended trading permissions you understand. The author's code and tests require no access to your secrets. A credential manager supplying the same environment variables is also supported.

## 5. Explicitly submit one order

After reading a fresh eligible preview, use its `plan_id` in place of `PLAN_ID`:

```bash
export POLYMARKET_STRATEGIES_LIVE=1
uv run polymarket-strategies trade submit trade-local.json --confirm PLAN_ID --live
```

Add `--prompt-credentials` only if the five values are neither in your environment nor saved by `trade setup`.

This is the money-moving step. Submission rechecks public rules/quotes, your balance and exchange allowance, and the live/geoblock/KILL guard. After signing it refreshes the preview again; changes to tick/size/fee constraints stop the post. No automatic allowance approval or POST retry occurs.

Before anything is sent, the command prints the market question, the outcome with its Polymarket label, the side, the limit price, the shares, the most pUSD that can be spent and the expiry, and asks you to type `YES`. It needs your own terminal. `--yes` skips the question for an order you have already reviewed; a script that passes `--yes` takes over the reading. Nothing in the software can check that you read the market's rules. The command also prints the ledger file and the kill-switch files it uses.

The SDK may return an accepted, resting, matched or delayed order. Acceptance does not mean every share filled or settlement succeeded. The local SQLite ledger is written before POST so a restart does not make a duplicate order appear new. An uncertain response blocks further submissions from that account in that ledger until reconciled. That includes the case where Polymarket reports the order as placed but returns no order ID. A refusal that proves nothing was placed (an HTTP 4xx error, a 503, a rate limit, or a refusal code such as not enough balance) is recorded as REJECTED, which does not block new orders.

## 6. Track fills, cancel and recover

Replace `INTENT_UUID` with the config's `intent_id`:

```bash
uv run polymarket-strategies trade status INTENT_UUID
uv run polymarket-strategies trade status INTENT_UUID --interval 5 --count 12
uv run polymarket-strategies trade cancel INTENT_UUID --confirm
uv run polymarket-strategies trade ledger
```

Add `--prompt-credentials` to `status`, `cancel`, `recover` or `resolve` too if neither your environment nor `trade setup` already provides the five account values. `ledger` reads only local records.

Status reconciles the actual order and account trades. It records filled quantities and prices, distinguishes pending, confirmed and failed settlement, and accounts for your own quantity when a trade contains several maker orders. A BUY fee is paid in pUSD on top of the price, so confirmed shares are delivered in full. `current_outcome_holdings` is the actual account balance, including prior positions, rather than a computed receipt estimate. Repeated polls update trades without recounting them. Fee values are estimates; the ledger is not a tax statement or a record of exact realized profit.

Cancellation requests removal of the unfilled remainder; shares already filled remain yours. Another fill can arrive while cancellation is being processed, so read status again. Creating a `KILL` file stops new submissions; it does not cancel resting orders, and it is checked only when a new order is about to be sent. Status and explicit cancellation remain available. The file belongs in the per-user state folder (`~/.polymarket-strategies/`, or the absolute folder named by `POLYMARKET_STRATEGIES_HOME`), so it works from any directory; a `KILL` file in the current folder also stops new orders. This command creates the first kind and prints where it is:

```bash
uv run python -c 'from polymarket_strategies.safety import state_dir; d = state_dir(); d.mkdir(parents=True, exist_ok=True); (d / "KILL").touch(); print(d / "KILL")'
uv run polymarket-strategies trade cancel INTENT_UUID --confirm
```

If an order submission times out, the process stops during POST, or Polymarket says the order was placed without giving its ID, **do not submit a replacement**. The command reports the outcome as unknown. Check your Polymarket account for the original order. Then ask the toolkit to look for it among your open orders in that market (it needs exactly one that matches the intent's token, side, price, size and expiry), or attach an exchange identifier you verified yourself:

```bash
uv run polymarket-strategies trade recover INTENT_UUID
uv run polymarket-strategies trade recover INTENT_UUID --order-id EXCHANGE_ORDER_ID
uv run polymarket-strategies trade status INTENT_UUID
```

Recovery checks the account and order fields against the recorded intent. It cannot prove that an ambiguous request never arrived. If the order was never placed (your account shows no order and no fill from it, and its expiry time plus two minutes has passed), close the intent so that new orders are allowed again:

```bash
uv run polymarket-strategies trade resolve INTENT_UUID --confirm
```

`resolve` refuses while the order could still be live, if an open order or a trade of your account still matches the intent, and if the account cannot be checked. A preparation stopped before POST can be aborted with `trade cancel INTENT_UUID --confirm`. A REJECTED or ABORTED intent has no order, so `status` and `recover` will tell you so.

`resolve` never closes an intent that already has an exchange order ID, because that order exists. If `recover` or `status` cannot verify such an order and its trade history, the intent keeps blocking new orders from that account. Check the order in your Polymarket account, cancel what is still resting there, and run `recover` or `status` again. Start a new ledger with `--ledger NEW_FILE` only after you have confirmed that nothing from the old intent is live or unsettled: the old file keeps the record, and its duplicate protection does not carry over to the new file.

Failed or uncertain authenticated commands print one error line (or, for an uncertain submission, a short JSON result) and return a nonzero exit status. A rejected public preview remains a successful diagnostic read. This distinction allows a shell workflow to stop without treating an uncertain submission as success. `status --count N` keeps polling after a failed check and exits nonzero at the end if any poll failed; it stops at once when no order exists.

Every account command uses one ledger per user, `~/.polymarket-strategies/orders.sqlite3` (or `orders.sqlite3` under the absolute folder `POLYMARKET_STRATEGIES_HOME`; a relative value is refused), and prints the path it uses, so the lifecycle does not depend on the folder you run from. `--ledger PATH` selects a different file; use the same path for the whole lifecycle. The ledger must be a regular file, not a folder or a link. Local records contain economic/account identifiers, not signing keys, API credentials or reusable signed orders. Back them up privately and protect local plans.

## What the commands contact

Public commands (`inspect`, `preview`, `watch`) read Polymarket's public APIs. Account commands also authenticate to Polymarket's trading API with your credentials. `check` (unless `--offline`) and `submit` ask Polymarket's geoblock endpoint whether your location may place orders. When your wallet is a smart wallet, the account check asks a public Polygon RPC node (the SDK's default, `polygon.drpc.org`) whether the wallet contract exists, which tells that provider your wallet address and your IP address. Both of these plain requests identify themselves as `polymarket-strategies`, because the servers refuse Python's default identification. Nothing is sent to the author.

## Verification and limits

Offline tests exercise partial fills, maker quantities, cancellation races, duplicate prevention, unknown POST responses and recovery using fake authenticated clients. They make no live trades. Software checks do not establish profitable forecasts, market comparability or trading eligibility.

The toolkit uses the official SDK pinned in `uv.lock`. If the platform/API changes, review the adapter before updating the dependency. Useful primary references: [order placement](https://docs.polymarket.com/trading/place-orders), [order management](https://docs.polymarket.com/trading/manage-orders), [trade settlement states](https://docs.polymarket.com/trading/realtime-order-updates), [fees](https://docs.polymarket.com/trading/fees).
