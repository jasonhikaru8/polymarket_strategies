"""A2 NegRisk bundle scanner: does buying every outcome of a multi-outcome event cost less than it pays? Read-only.

In a standard neg-risk event exactly one outcome wins. Buying one YES in every outcome pays $1; buying
one NO in every outcome pays n - 1. The live scanner excludes augmented events and events whose
augmentation status is unknown; all outcome legs must remain available and accepting orders.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys

from polymarket import AsyncPublicClient

from .baskets import buy_basket_profit, walk
from .data import asks_and_bids, books_by_token, run_public, yes_no_tokens
from .fees import schedule_from_market

_PLACEHOLDER = re.compile(r"\b(other|placeholder)\b|^(person|company|team|candidate|player)\s+[a-z]$", re.I)


def looks_augmented(labels: list[str]) -> bool:
    """True if any outcome label looks like 'Other' or a placeholder."""
    return any(_PLACEHOLDER.search(label or "") for label in labels)


def scan_event(markets, books) -> dict:
    """Executable buy-all-YES and buy-all-NO profit for one neg-risk event (markets are SDK Market objects)."""
    tokens = [yes_no_tokens(m) for m in markets]
    scheds = [schedule_from_market(m) for m in markets]
    n = len(markets)
    min_size = max(float(m.trading.minimum_order_size or 5) for m in markets)
    yes_asks = [asks_and_bids(books[t[0]])[0] for t in tokens]
    no_asks = [asks_and_bids(books[t[1]])[0] for t in tokens]
    return {
        "outcomes": n,
        "buy_all_yes": walk(yes_asks, buy_basket_profit(scheds, 1.0), min_size),
        "buy_all_no": walk(no_asks, buy_basket_profit(scheds, n - 1.0), min_size),
        "augmented_caution": looks_augmented([m.group_item_title or m.question for m in markets]),
    }


async def run(limit: int, notes: dict | None = None) -> tuple[int, list[dict]]:
    """(events actually scanned, events with executable profit)

    Reads one page of the 100 open events with the most 24-hour volume, keeps the standard neg-risk events with at least three
    outcomes that are all tradable, and scans the first `limit`. If you pass a dict as `notes`, it is filled with what was read and skipped.
    """
    notes = {} if notes is None else notes
    found: list[dict] = []
    scanned = no_book = unscannable = 0
    async with AsyncPublicClient() as client:
        page = (await client.list_events(closed=False, order="volume24hr", ascending=False, page_size=100).first_page()).items
        events = [e for e in page if e.markets and len(e.markets) >= 3
                  and getattr(getattr(e, "trading", None), "neg_risk_augmented", None) is False
                  and all(m.state.neg_risk is True and m.state.accepting_orders is True
                          and m.state.enable_order_book is True and yes_no_tokens(m) for m in e.markets)]
        notes.update(read=len(page), not_eligible=len(page) - len(events))
        events = events[:limit]
        books = await books_by_token(client, [t for e in events for m in e.markets for t in yes_no_tokens(m)])
        for e in events:
            if not all(t in books for m in e.markets for t in yes_no_tokens(m)):
                no_book += 1
                continue
            try:
                res = scan_event(e.markets, books)
            except ValueError:
                unscannable += 1  # unknown fees or invalid inputs cannot establish an executable profit
                continue
            scanned += 1
            if res["buy_all_yes"]["placeable"] or res["buy_all_no"]["placeable"]:
                found.append({"event": e.slug, "title": e.title, **res})
    notes.update(no_book=no_book, unscannable=unscannable)
    return scanned, found


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="polymarket-strategies negrisk-scan", description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=20, help="most events to scan, 1 to 100 (default 20); one page of the most active open events is read")
    args = ap.parse_args(argv)
    if not 1 <= args.limit <= 100:
        ap.error("--limit must be between 1 and 100: the scan reads one page of the 100 open events with the most 24-hour volume")
    notes: dict = {}
    scanned, hits = run_public("negrisk-scan", lambda: asyncio.run(run(args.limit, notes)))
    print(f"Read the {notes['read']} open events with the most 24-hour volume; {notes['not_eligible']} were not standard neg-risk events with three or more "
          f"tradable outcomes; scanned {scanned} (skipped {notes['no_book']} with a missing order book and {notes['unscannable']} with unknown fees or invalid data).", file=sys.stderr)
    print(json.dumps(hits, indent=2) if hits else f"Scanned {scanned} events: no executable NegRisk profit after fees.")
