"""Calculators, public readers and an explicitly enabled single-order trading toolkit."""
from __future__ import annotations

import argparse
import json
import math
import sys

from . import carry, fees, journal, sizing

SCANNERS = {
    "parity-scan": "parity_scan", "negrisk-scan": "negrisk_scan", "constraint-scan": "constraint_scan",
    "wallet-audit": "wallet_audit", "resolution-watch": "resolution_watch",
}


def _schedule_of_market(slug: str) -> fees.FeeSchedule:
    """The fee schedule a market carries in Polymarket's public data (read from the market; schedules can be attached after listing)."""
    import asyncio

    from polymarket import AsyncPublicClient

    async def fetch():
        async with AsyncPublicClient() as client:
            for closed in (False, True):  # the SDK leaves out closed markets unless asked
                items = (await client.list_markets(slug=[slug], closed=closed, page_size=2).first_page()).items
                found = [m for m in items if m.slug == slug]  # only the exact slug counts
                if found:
                    return fees.schedule_from_market(found[0])
        raise ValueError(f"no market with the slug {slug!r}")

    return asyncio.run(fetch())


def _calc(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="polymarket-strategies calc", description="Fee, carry and Kelly arithmetic")
    ap.add_argument("--category", choices=sorted(fees.CATEGORY_FEES), help="fee category (default politics; the schedule used is printed)")
    ap.add_argument("--rate", type=float, help="the market's own taker fee rate, e.g. 0.05 (replaces the category's)")
    ap.add_argument("--slug", help="read the market's own fee schedule from Polymarket's public data (needs the network)")
    ap.add_argument("--price", type=float, required=True, help="price per share, 0 to 1")
    ap.add_argument("--shares", type=float, default=100)
    ap.add_argument("--days", type=float, help="days to resolution, at least 1, for annualized carry")
    ap.add_argument("--prob", type=float, help="your true probability, for Kelly sizing")
    a = ap.parse_args(argv)
    if not math.isfinite(a.price) or not math.isfinite(a.shares) or not 0 < a.price < 1 or a.shares <= 0:
        ap.error("price must be between 0 and 1, and shares must be positive")
    if a.days is not None and (not math.isfinite(a.days) or a.days < 1):
        ap.error("days must be at least 1: a shorter period annualizes into a meaningless number")
    if a.prob is not None and (not math.isfinite(a.prob) or not 0 <= a.prob <= 1):
        ap.error("prob must be between 0 and 1")
    if a.rate is not None and (not math.isfinite(a.rate) or a.rate < 0):
        ap.error("rate must be nonnegative")
    if a.slug:
        from .data import run_public

        try:
            sched, source = run_public("calc", lambda: _schedule_of_market(a.slug)), f"the market {a.slug!r}"
        except ValueError as error:
            ap.error(str(error))
    elif a.rate is not None:
        sched, source = fees.FeeSchedule(rate=a.rate), "--rate"
    elif a.category:
        sched, source = fees.schedule_for(a.category), f"the {a.category} category"
    else:
        sched, source = fees.schedule_for("politics"), "the politics category (the default: pass --category, --rate or --slug for your market)"
    fee = fees.fee_per_share(a.price, sched)
    if a.price + fee >= 1:
        ap.error("entry cost including the fee must be below the maximum $1 payout")
    out = {"fee_schedule": {"source": source, "taker_rate": sched.rate, "exponent": sched.exponent,
                     "maker_rebate_share": None if a.rate is not None else sched.rebate_rate},  # unknown when only the taker rate was given
           "taker_fee_usdc": fees.taker_fee(a.shares, a.price, sched), "fee_fraction_of_cost": fees.fee_fraction_of_cost(a.price, sched),
           "break_even_probability": fees.min_true_probability(a.price, sched),
           "return_if_win": carry.return_if_win(a.price, fee), "wins_canceled_by_one_loss": carry.wins_needed_per_loss(a.price, fee)}
    if a.days is not None:
        try:
            out["annualized_if_win"] = carry.annualized(out["return_if_win"], a.days)
        except ValueError as error:
            ap.error(f"{error}; use a longer period or leave --days out")
    if a.prob is not None:
        full = sizing.kelly_fraction(a.prob, a.price, fee)
        out["kelly_full"], out["kelly_quarter_capped"] = full, sizing.fractional_kelly(full)
    print(json.dumps({key: round(value, 6) if isinstance(value, float) else value for key, value in out.items()}, indent=2))  # no float noise


def _journal(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="polymarket-strategies journal-summary", description="Summarize a paper-decision journal (JSONL)")
    ap.add_argument("path")
    ap.add_argument("--strategy", help="summarize only this strategy's decisions (default: all in the file, pooled)")
    a = ap.parse_args(argv)
    try:
        summary = journal.summarize(a.path, strategy=a.strategy)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        ap.error(f"cannot summarize {a.path}: {error}")
    print(json.dumps(summary, indent=2, default=str))


HELP = """usage: polymarket-strategies COMMAND [options]

commands:
  calc              fee, break-even, carry and Kelly arithmetic for one price
  journal-summary   summarize a paper-decision journal
  trade             setup, check, inspect, approve, preview, submit, track and cancel one reader-approved limit order
  strategy          list, show an example for, analyze and prepare the 35 strategy tools
  parity-scan, negrisk-scan, constraint-scan, wallet-audit, resolution-watch
                    read-only tools that read public Polymarket data

Run `polymarket-strategies COMMAND --help` for a command's options."""


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    cmds = ["calc", "journal-summary", "trade", "strategy", *SCANNERS]
    if argv and argv[0] in ("-h", "--help"):
        print(HELP)
        return
    if argv and argv[0] == "--version":
        from importlib.metadata import version
        print(version("polymarket-strategies"))
        return
    if not argv or argv[0] not in cmds:
        print(HELP if not argv else HELP.splitlines()[0] + "\nrun with --help to list the commands", file=sys.stderr)
        sys.exit(2)
    cmd, rest = argv[0], argv[1:]
    if cmd == "calc":
        _calc(rest)
    elif cmd == "journal-summary":
        _journal(rest)
    elif cmd == "trade":
        from .trading_cli import main as trade_main
        trade_main(rest)
    elif cmd == "strategy":
        from .strategy_cli import main as strategy_main
        strategy_main(rest)
    else:
        __import__(f"polymarket_strategies.{SCANNERS[cmd]}", fromlist=["main"]).main(rest)


if __name__ == "__main__":
    main()
