"""A1 Binary parity scanner: is a complete set (YES + NO) executable below or above $1 after fees? Read-only.

Buy side: buy YES and NO as a taker; a pair always redeems for $1.
Sell side: split $1 into a pair (no Polymarket fee on the split) and sell both into bids.
Neg-risk markets are included; their split and merge go through the neg-risk collateral adapter.
Most markets show nothing. That is the finding: this edge is thin and bot-dominated.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from polymarket import AsyncPublicClient

from .baskets import buy_basket_profit, sell_basket_profit, walk
from .data import asks_and_bids, books_by_token, run_public, yes_no_tokens
from .fees import FeeSchedule, schedule_from_market


def scan_pair(yes_book, no_book, schedule: FeeSchedule, min_size: float = 5.0) -> dict:
    """Executable buy-side and sell-side profit for one binary market's two order books."""
    yes_asks, yes_bids = asks_and_bids(yes_book)
    no_asks, no_bids = asks_and_bids(no_book)
    scheds = [schedule, schedule]
    buy = walk([yes_asks, no_asks], buy_basket_profit(scheds), min_size)
    sell = walk([yes_bids, no_bids], sell_basket_profit(scheds), min_size)
    top = {"ask_sum": yes_asks[0][0] + no_asks[0][0] if yes_asks and no_asks else None,
           "bid_sum": yes_bids[0][0] + no_bids[0][0] if yes_bids and no_bids else None}
    return {"buy_pair": buy, "mint_and_sell": sell, "top_of_book": top}


async def run(limit: int, notes: dict | None = None) -> tuple[int, list[dict], list[dict]]:
    """(markets actually scanned, markets with executable profit, the closest misses)

    Reads one page of the 100 open markets with the most 24-hour volume, keeps those that are tradable, and scans the first `limit`.
    If you pass a dict as `notes`, it is filled with what was read and what was skipped.
    """
    notes = {} if notes is None else notes
    found: list[dict] = []
    near: list[dict] = []
    scanned = no_book = unknown_fees = 0
    async with AsyncPublicClient() as client:
        pages = client.list_markets(closed=False, order="volume24hr", ascending=False, page_size=100)
        page = (await pages.first_page()).items
        markets = [m for m in page if m.state.accepting_orders is True and m.state.enable_order_book is True and yes_no_tokens(m)]
        notes.update(read=len(page), not_tradable=len(page) - len(markets))
        markets = markets[:limit]
        books = await books_by_token(client, [t for m in markets for t in yes_no_tokens(m)])
        for m in markets:
            yes_id, no_id = yes_no_tokens(m)
            if yes_id not in books or no_id not in books:
                no_book += 1
                continue
            try:
                schedule = schedule_from_market(m)
            except ValueError:
                unknown_fees += 1  # an unknown fee schedule cannot establish an executable profit
                continue
            scanned += 1
            res = scan_pair(books[yes_id], books[no_id], schedule,
                            float(m.trading.minimum_order_size or 5))
            row = {"market": m.slug, "question": m.question, "neg_risk": m.state.neg_risk, **res}
            if res["buy_pair"]["placeable"] or res["mint_and_sell"]["placeable"]:
                found.append(row)
            top = res["top_of_book"]
            if top["ask_sum"] is not None and top["bid_sum"] is not None:
                near.append({"market": m.slug, "ask_sum": round(top["ask_sum"], 4), "bid_sum": round(top["bid_sum"], 4),
                             "gap_before_fees": round(min(top["ask_sum"] - 1, 1 - top["bid_sum"]), 4)})
    notes.update(no_book=no_book, unknown_fees=unknown_fees)
    near.sort(key=lambda r: r["gap_before_fees"])
    return scanned, found, near[:5]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="polymarket-strategies parity-scan", description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=50, help="most markets to scan, 1 to 100 (default 50); one page of the most active open markets is read")
    args = ap.parse_args(argv)
    if not 1 <= args.limit <= 100:
        ap.error("--limit must be between 1 and 100: the scan reads one page of the 100 open markets with the most 24-hour volume")
    notes: dict = {}
    scanned, hits, near = run_public("parity-scan", lambda: asyncio.run(run(args.limit, notes)))
    print(f"Read the {notes['read']} open markets with the most 24-hour volume; {notes['not_tradable']} were not accepting orders or not binary; "
          f"scanned {scanned} (skipped {notes['no_book']} without an order book and {notes['unknown_fees']} with an unknown fee schedule).", file=sys.stderr)
    if hits:
        print(json.dumps(hits, indent=2))
    else:
        print(f"Scanned {scanned} markets: no executable parity profit after fees. Closest to parity (gap before fees; negative = a raw gap):")
        print(json.dumps(near, indent=2))
