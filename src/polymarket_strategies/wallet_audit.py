"""F1 Wallet audit: is a wallet's record copyable, or only impressive? Read-only, public on-chain data.

Counts distinct events among its buys (not fills; the book calls these independent decisions), shows the price distribution of its
buys, and flags records dominated by 90c+ purchases or by one lucky position. Copiers buy later and pay fees, so a 97c buy wins
about 3c (before fees) and loses about 97c.

Scope, printed in every result: it reads TAKER fills only (trades where the wallet took liquidity, not fills of its resting
orders), so a wallet that mostly posts orders is described by a small part of its activity. Profit figures are the positions feed's
`total_pnl`: realized plus unrealized, with open positions marked to the current price. They are not settled results.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re

from polymarket import AsyncPublicClient

from .data import run_public

ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")  # a public wallet address: 0x and 40 hexadecimal characters


def audit(trades: list[dict], positions: list[dict]) -> dict:
    """Pure summary from plain dicts: trades {side, size, price, event}, positions {total_pnl}."""
    buys = [t for t in trades if t["side"].upper() == "BUY"]
    usd = sum(t["size"] * t["price"] for t in buys)
    share = lambda lo: (sum(t["size"] * t["price"] for t in buys if t["price"] >= lo) / usd) if usd else 0.0  # noqa: E731
    wins = [p["total_pnl"] for p in positions if p["total_pnl"] > 0]
    losses = [p["total_pnl"] for p in positions if p["total_pnl"] < 0]
    top_share = (max(wins) / sum(wins)) if wins else 0.0
    independent = len({t["event"] for t in buys})
    flags = []
    if independent < 100:
        flags.append("fewer than 100 distinct events among its buys: too few to judge skill")
    if share(0.90) > 0.5:
        flags.append("over half of buy dollars are at 90c or more: a late copier wins cents and can lose most of the stake")
    if top_share > 0.5:
        flags.append("one position is over half of all gains: the record may be one lucky bet")
    return {
        "buy_fills": len(buys), "distinct_events": independent,
        "buy_dollars": round(usd, 2),
        "share_of_buy_dollars_ge_75c": round(share(0.75), 3), "share_of_buy_dollars_ge_90c": round(share(0.90), 3),
        "positions": len(positions), "positions_in_profit": len(wins), "net_pnl": round(sum(p["total_pnl"] for p in positions), 2),
        "profit_factor": round(sum(wins) / -sum(losses), 3) if losses else None,
        "largest_win_share_of_gains": round(top_share, 3), "flags": flags,
        "scope": "taker fills only (trades where this wallet took liquidity), all history, most recent first; not its resting-order fills",
        "pnl_basis": "positions' total_pnl = realized plus unrealized: open positions are marked to the current price, not settled",
    }


async def run(wallet: str, limit: int) -> dict:
    """Read trades and positions in BOTH books. The default position list omits closed positions, which
    silently drops the winners that were sold or redeemed and makes every wallet look like a loser. OPEN is
    already the superset of REDEEMABLE (settled but unredeemed), so asking for REDEEMABLE too would count
    those positions twice."""
    async with AsyncPublicClient() as client:
        trades, positions, truncated = [], {}, False
        # taker_only and full_history are stated, not left to the API's defaults: the book's wallet audits count taker fills only, and
        # without full_history the trades feed applies its own default time window
        async for t in client.list_trades(user=wallet, taker_only=True, full_history=True, page_size=100).iter_items():
            if len(trades) >= limit:
                truncated = True  # there is at least one more row beyond the limit
                break
            trades.append({"side": str(getattr(t.side, "value", t.side)), "size": float(t.size),
                           "price": float(t.price), "event": t.event_slug or t.slug})
        for status in ("OPEN", "CLOSED"):
            n = 0
            # the API's default order is biggest realized profit first, so a truncated read would hold only winners: ask for the most recent instead
            async for p in client.list_positions(user=wallet, status=status, sort_by="TIMESTAMP", sort_direction="DESC", page_size=100).iter_items():
                if n >= limit:
                    truncated = True
                    break
                positions.setdefault(str(p.asset_id), {"total_pnl": float(p.total_pnl or 0)})
                n += 1
    out = audit(trades, list(positions.values()))
    out["truncated_at_limit"] = truncated
    if truncated:
        out["flags"].append(f"read at most {limit} trades and {limit} positions per book: results describe the most recent of them")
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="polymarket-strategies wallet-audit", description=__doc__.splitlines()[0])
    ap.add_argument("wallet", help="0x wallet address (public data)")
    ap.add_argument("--limit", type=int, default=1000, help="max trades and positions to read (default 1000)")
    args = ap.parse_args(argv)
    if args.limit < 1:
        ap.error("--limit must be at least 1")
    if not ADDRESS.fullmatch(args.wallet):  # checked before any request, so a placeholder such as 0x... is never sent
        ap.error(f"{args.wallet!r} is not a wallet address: give 0x followed by 40 hexadecimal characters (0-9, a-f)")
    print(json.dumps(run_public("wallet-audit", lambda: asyncio.run(run(args.wallet, args.limit))), indent=2))
