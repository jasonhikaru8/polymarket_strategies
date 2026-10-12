"""A3/A4 Constraint scanner: markets you say are logically nested should not be priced inconsistently. Read-only.

If "smaller" implies "larger" (for example "by June" and "by December", or "candidate wins" and "party wins"),
then YES(larger) + NO(smaller) always pays at least $1. If that pair costs less than $1 after fees, the prices
are inconsistent. YOU are responsible for the implication being true under both markets' resolution rules;
semantic differences between markets are the main way this "arbitrage" turns into a loss.

Constraints file (JSON): [{"smaller": "market-slug-a", "larger": "market-slug-b"}]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from polymarket import AsyncPublicClient

from .baskets import buy_basket_profit, walk
from .data import asks_and_bids, books_by_token, run_public, yes_no_tokens
from .fees import schedule_from_market
from .jsonfile import read_json_text


async def run(constraints: list[dict]) -> list[dict]:
    out: list[dict] = []
    async with AsyncPublicClient() as client:
        slugs = list({s for c in constraints for s in (c["smaller"], c["larger"])})
        markets = {m.slug: m for i in range(0, len(slugs), 100)  # the API returns at most 100 markets a call
                   for m in (await client.list_markets(slug=slugs[i:i + 100], page_size=100).first_page()).items}
        books = await books_by_token(client, [t for m in markets.values()
                                            if m.state.accepting_orders is True and m.state.enable_order_book is True
                                            for t in (yes_no_tokens(m) or ())])
        for c in constraints:
            small, large = markets.get(c["smaller"]), markets.get(c["larger"])
            if not small or not large or not yes_no_tokens(small) or not yes_no_tokens(large):
                out.append({**c, "error": "market not found (closed markets are not read) or not binary"})
                continue
            if not all(m.state.accepting_orders is True and m.state.enable_order_book is True for m in (small, large)):
                out.append({**c, "error": "market is not accepting orders or has no enabled order book"})
                continue
            token_ids = [yes_no_tokens(large)[0], yes_no_tokens(small)[1]]
            if not all(t in books for t in token_ids):
                out.append({**c, "error": "required order book is unavailable"})
                continue
            try:
                scheds = [schedule_from_market(large), schedule_from_market(small)]
            except ValueError as error:
                out.append({**c, "error": str(error)})
                continue
            legs = [asks_and_bids(books[t])[0] for t in token_ids]
            min_size = max(float(m.trading.minimum_order_size or 5) for m in (small, large))
            out.append({**c, **walk(legs, buy_basket_profit(scheds, 1.0), min_size)})
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="polymarket-strategies constraint-scan", description=__doc__.splitlines()[0])
    ap.add_argument("constraints", type=Path, help="JSON file of {smaller, larger} slug pairs")
    args = ap.parse_args(argv)
    try:
        constraints = json.loads(read_json_text(args.constraints))
        if not (isinstance(constraints, list) and all(isinstance(c, dict) and isinstance(c.get("smaller"), str) and isinstance(c.get("larger"), str)
                                                      for c in constraints)):
            raise ValueError("the file must hold a list of {\"smaller\": slug, \"larger\": slug} pairs")
    except (OSError, ValueError) as error:
        ap.error(f"cannot use {args.constraints}: {error}")
    print(json.dumps(run_public("constraint-scan", lambda: asyncio.run(run(constraints))), indent=2))
