"""Inspect, preview, submit, reconcile and cancel a reader-selected limit order."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from getpass import GetPassWarning, getpass
from pathlib import Path

from . import account_setup, safety, trade_plan
from .data import NETWORK_ERRORS, network_failure
from .execution import ExecutionError
from .jsonfile import read_json_text
from .safety import NotAllowed

KINDS = ("manual", "model_value", "favorite_carry", "mention_base_rate")
PUBLIC_COMMANDS = ("inspect", "preview", "watch", "approve")  # read public data only: no credentials, no ledger
NEEDS_ACCOUNT = ("submit", "status", "cancel", "recover", "resolve", "check")  # these read the saved credentials file
ACCOUNT_FAILURE = "Operation failed. No automatic resubmission. Check the local ledger and account before retrying.\n"
CREDENTIAL_NAMES = account_setup.CREDENTIAL_NAMES


def load_config(path: str) -> dict:
    def bad_number(value):
        raise ValueError("Nonfinite JSON numbers are not allowed")
    value = json.loads(read_json_text(path), parse_constant=bad_number)
    if not isinstance(value, dict):
        raise ValueError("Configuration must be a JSON object")
    allowed = {"intent_id", "market_slug", "outcome", "side", "shares", "limit_price", "expires_at",
               "post_only", "limits", "approval", "strategy"}
    if set(value) - allowed:
        raise ValueError("Unexpected configuration fields; credentials belong only in local environment variables")
    return value


def default_ledger() -> str:
    """One ledger per user, so every command finds the same record whatever folder it is run from."""
    return str(safety.state_dir() / "orders.sqlite3")


def output(value: dict) -> None:
    print(json.dumps(value, indent=2, allow_nan=False))


def account_output(value: dict) -> None:
    output(value)
    if value.get("ok") is not True:
        raise SystemExit(1)


async def run(args) -> None:
    if args.command == "inspect":
        for name, value, positive in (("shares", args.shares, True), ("price", args.price, True), ("max-cash", args.max_cash, False)):
            if value is not None:
                trade_plan.decimal(value, name, positive=positive)
        inspected = await trade_plan.inspect(args.slug)
        config = trade_plan.draft_config(inspected, kind=args.strategy, outcome=args.outcome, side=args.side,
                                         shares=args.shares, limit_price=args.price or "0.50", max_cash=args.max_cash)
        if args.out:
            target = Path(args.out)
            # Never overwrite an already reviewed plan by accident.
            with target.open("x", encoding="utf-8") as f:
                json.dump(config, f, indent=2, allow_nan=False)
                f.write("\n")
        output({"contract": inspected["contract"], "fingerprint": inspected["fingerprint"],
                "state": inspected["state"], "unapproved_config": config,
                "next_step": f"Read the rules, then approve them with `trade approve {args.out or 'FILE'}` (or edit the config yourself), then `trade preview`."})
    elif args.command == "approve":
        await approve(args.config, args.minutes)
    elif args.command == "check":
        result = await account_setup.check(args.saved, offline=args.offline)
        output(result)
        if not result["ready"]:
            raise SystemExit(1)
    elif args.command in ("preview", "watch"):
        config = load_config(args.config)
        count = args.count if args.command == "watch" else 1
        for index in range(count):
            output(await trade_plan.preview(config))
            if index + 1 < count:
                await asyncio.sleep(args.interval)
    else:
        from . import execution
        ledger = args.ledger or default_ledger()
        print(f"ledger: {ledger}", file=sys.stderr)
        if args.command == "submit":
            print("kill-switch files checked: " + ", ".join(str(p) for p in safety.kill_files()), file=sys.stderr)
            print(safety.DISCLAIMER, file=sys.stderr)
            config = load_config(args.config)
            if not args.live:
                raise NotAllowed("dry run: pass --live to enable live orders (checked before anything is shown or typed)")
            if not args.yes:
                await confirm_in_terminal(config, args.confirm)
            account_output(await execution.submit(config, ledger, confirm=args.confirm, live=args.live))
        elif args.command == "status":
            failed = False
            for index in range(args.count):
                result = await execution.status(args.intent_id, ledger)
                output(result)
                failed = failed or result.get("ok") is not True
                if result.get("ok") is not True and result.get("trades_complete") is not False:
                    break  # no order exists for this intent, so waiting changes nothing; a failed check (trades_complete false) is worth repeating
                if index + 1 < args.count:
                    await asyncio.sleep(args.interval)
            if failed:
                raise SystemExit(1)
        elif args.command == "cancel":
            account_output(await execution.cancel(args.intent_id, ledger, confirm=args.confirm))
        elif args.command == "recover":
            account_output(await execution.recover(args.intent_id, args.order_id, ledger))
        elif args.command == "resolve":
            account_output(await execution.resolve(args.intent_id, ledger, confirm=args.confirm))
        elif args.command == "ledger":
            output(execution.local_summary(ledger))


async def confirm_in_terminal(config: dict, plan_id: str) -> None:
    """Show what is about to be sent and ask for a typed YES. Nothing here can check that you read the rules."""
    if not sys.stdin.isatty():
        raise ValueError("Submitting asks for a typed confirmation in a terminal; pass --yes only if you have already reviewed this order")
    preview = await trade_plan.preview(config)
    if not preview["eligible"] or preview["plan_id"] != plan_id:
        raise ExecutionError("An eligible fresh preview and its exact plan ID are required.")
    order, contract = preview["order"], preview["contract"]
    when = datetime.fromtimestamp(order["expiration"], timezone.utc).astimezone().isoformat(timespec="minutes")
    risk = (f"At most {preview['cash_bound']} pUSD at risk" if order["side"] == "BUY"
            else f"Sells {order['size']} shares at no less than the limit price; the fee comes out of the proceeds")
    print(f"Market:  {contract['question']}\nOutcome: {config['outcome']} ({contract['labels'][config['outcome']]})   Side: {order['side']}\n"
          f"Limit price {order['price']}   Shares {order['size']}   {risk}   Expires {when}", file=sys.stderr)
    if input("Type YES to place this order: ").strip() != "YES":
        raise ExecutionError("Not confirmed; no order was sent.")


def prompt_credentials() -> None:
    """Terminal-only entry for this process; never write a credential file or echo secrets."""
    if not sys.stdin.isatty():
        raise ValueError("Credential prompting requires your own interactive terminal")
    for name in CREDENTIAL_NAMES:
        if not os.environ.get(name):
            with warnings.catch_warnings():
                warnings.simplefilter("error", GetPassWarning)
                value = input(f"{name}: ") if name == "POLYMARKET_WALLET_ADDRESS" else getpass(f"{name}: ")
            if not value:
                raise ValueError("All five local account values are required")
            os.environ[name] = value


async def approve(path: str, minutes: int) -> None:
    """Terminal-only review: show the market's current public rules, take your own words for what YES means, then mark the config approved."""
    if not sys.stdin.isatty():
        raise ValueError("Approving asks you to read the rules and type your answers in your own interactive terminal")
    config = load_config(path)
    inspected = await trade_plan.inspect(config["market_slug"])
    contract, outcome = inspected["contract"], config["outcome"]
    ends = datetime.fromtimestamp(contract["end_time"], timezone.utc).astimezone().isoformat(timespec="minutes")
    print(f"{contract['question']}\n\n{contract['description']}\n\nSource named: {contract['resolution_source'] or 'none listed: find it in the rules above'}\n"
          f"Ends: {ends}\nYour order: {config['side']} {config['shares']} shares of {outcome} ({contract['labels'][outcome]}) at no more than "
          f"{config['limit_price']}; spending limit {config['limits']['max_cash']} pUSD", file=sys.stderr)
    inputs = (config.get("strategy") or {}).get("inputs") or {}
    own = {**(inputs.get("parameters") or {}), **inputs}  # the strategy's own YES definition and source, which the approval must match
    forecast_end = own.get("valid_until")  # an approval never outlasts the market or the forecast it rests on
    ends_at = min([contract["end_time"], *([forecast_end] if isinstance(forecast_end, (int, float)) else [])])
    too_soon = "The market or the forecast ends within five minutes, too soon for an order; the config is unchanged"
    if ends_at < time.time() + 300:
        raise ValueError(too_soon)
    hint = f" [Enter keeps: {own['target_yes_definition']}]" if own.get("target_yes_definition") else ""
    definition = input(f"What exactly must happen for YES?{hint} ").strip() or own.get("target_yes_definition", "")
    source = contract["resolution_source"] or input("Which source decides the outcome (it is named in the rules)? ").strip() or own.get("resolution_source", "")
    note = input("Why does this market fit your strategy? ").strip()
    if not (definition and source and note):
        raise ValueError("A definition, a source and a note are all required; the config is unchanged")
    if input(f"Type APPROVE to approve these rules for {minutes} minutes: ").strip() != "APPROVE":
        raise ExecutionError("Not approved; the config is unchanged.")
    now = time.time()  # the approval starts when you approve, not when you started reading; so does a too-close expiry's fresh window
    valid_until = min(now + minutes * 60, ends_at)
    if valid_until < now + 300:
        raise ValueError(too_soon)
    config["approval"] = {**config["approval"], "approved": True, "fingerprint": inspected["fingerprint"], "reviewed_at": now,
                          "valid_until": valid_until, "resolution_source": source, "yes_definition": definition, "note": note}
    expiry = config["expires_at"]
    if expiry < now + 300:  # the platform needs about three minutes of lead time: start a fresh eleven-minute window
        expiry = int(now) + 660
    expiry = min(expiry, int(valid_until))  # an order never outlasts its approval
    if expiry != config["expires_at"]:
        print(f"The order's expiry is now {expiry} (Unix seconds).", file=sys.stderr)
    config["expires_at"] = expiry
    temp = Path(path).with_name(Path(path).name + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, allow_nan=False)
        handle.write("\n")
    os.replace(temp, path)
    print(f"Approved until {datetime.fromtimestamp(valid_until).isoformat(timespec='minutes')}. Next: trade preview {path}", file=sys.stderr)


def setup() -> None:
    """Ask (hidden) for the account values still missing and offer to save them to your private credentials file."""
    if not sys.stdin.isatty():
        raise ValueError("Setup asks for your account values in your own interactive terminal")
    print(safety.DISCLAIMER, file=sys.stderr)
    saved = account_setup.read_saved()
    loaded = account_setup.load_saved()
    before = {name for name in CREDENTIAL_NAMES if os.environ.get(name)}
    prompt_credentials()
    typed = {name: os.environ[name] for name in CREDENTIAL_NAMES if name not in before}
    path = account_setup.credentials_file()
    if typed:
        print(f"Saving writes your values unencrypted to {path}, readable only by you. Skip it if you would rather use your own "
              "credential manager or environment variables.", file=sys.stderr)
        if input("Type yes to save them there: ").strip().lower() == "yes":
            account_setup.save({**saved, **typed})
            print(f"Saved to {path}", file=sys.stderr)
        else:
            print("Not saved; they were used for this check only.", file=sys.stderr)
    output(asyncio.run(account_setup.check(loaded, offline=True)))
    print("Next: trade check (reads your pUSD balance), then trade inspect MARKET_SLUG --out trade.json", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="polymarket-strategies trade", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Enter your account values once; optionally save them in a private file")
    check = sub.add_parser("check", help="Is the account ready? Credentials, location, pUSD balance and allowance")
    check.add_argument("--offline", action="store_true", help="local checks only: no location check, no login")
    check.add_argument("--prompt-credentials", action="store_true", help="Read missing credentials privately in your terminal for this process only")
    inspect = sub.add_parser("inspect", help="Public full rules, fingerprint and unapproved template")
    inspect.add_argument("slug")
    inspect.add_argument("--strategy", choices=KINDS, default="manual")
    inspect.add_argument("--out", help="Create a new config file; refuses to overwrite an existing file")
    inspect.add_argument("--outcome", choices=("YES", "NO"), default="YES")
    inspect.add_argument("--side", choices=("BUY", "SELL"), default="BUY")
    inspect.add_argument("--shares", help="order size in shares (also sets the share limit)")
    inspect.add_argument("--price", help="limit price per share, such as 0.40")
    inspect.add_argument("--max-cash", help="most pUSD this order may cost, fee reserve included")
    approve_parser = sub.add_parser("approve", help="Read the current rules in your terminal and approve a config (no hand editing)")
    approve_parser.add_argument("config")
    approve_parser.add_argument("--minutes", type=int, default=60, help="how long the approval lasts, 10 to 1440 (default 60)")
    for name in ("preview", "watch", "submit"):
        parser = sub.add_parser(name, help={"preview": "Public preview; no signer or order",
                                           "watch": "Repeated public previews; never submits",
                                           "submit": "Explicitly submit one approved, bounded GTD limit order"}[name])
        parser.add_argument("config")
        if name == "watch":
            parser.add_argument("--interval", type=float, default=5)
            parser.add_argument("--count", type=int, default=12)
        if name == "submit":
            parser.add_argument("--confirm", required=True, help="plan_id printed by the preview")
            parser.add_argument("--live", action="store_true")
            parser.add_argument("--yes", action="store_true", help="skip the typed confirmation (for a reviewed order only)")
            parser.add_argument("--ledger", help="order ledger file (default: one per user, see the printed path)")
            parser.add_argument("--prompt-credentials", action="store_true", help="Read missing credentials privately in your terminal for this process only")
    for name in ("status", "cancel", "recover", "resolve"):
        parser = sub.add_parser(name, help={"status": "Reconcile the order and its fills", "cancel": "Cancel the unfilled remainder",
                                           "recover": "Attach the exchange order to an unresolved intent",
                                           "resolve": "Close an unresolved intent after its order expired with no order or fill"}[name])
        parser.add_argument("intent_id", help="the config's UUID, not the exchange order ID")
        parser.add_argument("--ledger", help="order ledger file (default: one per user, see the printed path)")
        parser.add_argument("--prompt-credentials", action="store_true", help="Read missing credentials privately in your terminal for this process only")
        if name == "status":
            parser.add_argument("--interval", type=float, default=5)
            parser.add_argument("--count", type=int, default=1)
        if name == "cancel":
            parser.add_argument("--confirm", action="store_true", help="explicitly cancel the unfilled remainder")
        if name == "resolve":
            parser.add_argument("--confirm", action="store_true", help="you checked your account: no order or fill exists for this intent")
        if name == "recover":
            parser.add_argument("--order-id", help="exchange ID you verified belongs to the uncertain submission (default: look for the one matching open order)")
    ledger = sub.add_parser("ledger", help="Local economic records; no account connection")
    ledger.add_argument("--ledger", help="order ledger file (default: one per user)")
    args = ap.parse_args(argv)
    if hasattr(args, "count") and not 1 <= args.count <= 10000:
        ap.error("count must be between 1 and 10000")
    if hasattr(args, "interval") and not 1 <= args.interval <= 60:
        ap.error("interval must be between 1 and 60 seconds")
    if hasattr(args, "minutes") and not 10 <= args.minutes <= 1440:
        ap.error("minutes must be between 10 and 1440")
    previous = {name: os.environ.get(name) for name in CREDENTIAL_NAMES}
    try:
        if args.command == "setup":
            try:
                setup()
            except OSError as error:
                raise ValueError(f"could not write the credentials file: {error.strerror}") from None
            return
        if args.command in NEEDS_ACCOUNT:
            args.saved = account_setup.load_saved()  # values already in the environment win; --prompt-credentials fills what is still missing
        if getattr(args, "prompt_credentials", False):
            if args.command == "submit":
                from .safety import require_live
                require_live(args.live)
            if args.command == "cancel" and not args.confirm:
                ap.error("Cancellation requires --confirm")
            if args.command == "resolve" and not args.confirm:
                ap.error("Resolving requires --confirm")
            prompt_credentials()
        asyncio.run(run(args))
    except (ValueError, FileExistsError, FileNotFoundError) as error:
        ap.error(str(error))
    except (ExecutionError, NotAllowed) as error:
        ap.exit(1, f"{error}\n")
    except NETWORK_ERRORS as error:
        if args.command not in PUBLIC_COMMANDS:
            ap.exit(1, ACCOUNT_FAILURE)  # an account command's network failure leaves the order's fate unknown
        ap.exit(1, f"trade {args.command}: {network_failure(error)}\n")
    except Exception as error:
        if args.command in PUBLIC_COMMANDS:
            # A read-only lookup has no ledger and no credentials; name only the kind of error.
            ap.exit(1, f"trade {args.command}: the read-only lookup failed ({type(error).__name__}). It placed no order; check the slug or file and try again.\n")
        # Authenticated SDK exceptions can contain request material. Don't print them.
        ap.exit(1, ACCOUNT_FAILURE)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    main()
