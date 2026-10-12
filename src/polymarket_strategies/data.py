"""Shared helpers for reading market data through the Polymarket SDK (`polymarket-client`, pre-1.0).

Five read-only tools (constraint_scan, negrisk_scan, parity_scan, resolution_watch, wallet_audit) build their own `AsyncPublicClient` too, so if the SDK changes, check each of these modules.
Everything is read-only and needs no keys. `run_public` turns a network error in these tools into one plain line and exit status 1.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
import http.client
import sys
from typing import TypeVar
import urllib.error

from polymarket import AsyncPublicClient, ProtocolVersion
from polymarket._internal.protocol import is_v2_position_id
from polymarket.errors import RateLimitError, RequestRejectedError, TransportError

from .baskets import Level

T = TypeVar("T")
# Failures to read Polymarket's public data: the SDK's network, refusal and rate-limit errors, and urllib's for the plain requests.
NETWORK_ERRORS = (TransportError, RequestRejectedError, RateLimitError, urllib.error.URLError, http.client.HTTPException,
                  ConnectionError, TimeoutError)


def network_failure(error: BaseException) -> str:
    """One plain sentence for a read-only command that could not read Polymarket's public data."""
    if isinstance(error, urllib.error.HTTPError):
        detail = f"HTTP {error.code} {error.reason}"
    elif isinstance(error, urllib.error.URLError):
        detail = str(error.reason)
    elif isinstance(error, RequestRejectedError):
        detail = f"HTTP {error.status}: {error}"
    else:
        detail = str(error) or type(error).__name__
    detail = " ".join(detail.split())  # one line, whatever the server sent
    if len(detail) > 160:
        detail = detail[:157] + "..."
    return (f"could not read Polymarket's public data ({detail}). Check your network connection and try again; "
            "this command only reads public data and placed no order.")


def run_public(prog: str, call: Callable[[], T]) -> T:
    """Run a read-only command's network step. On a network error, print one plain line instead of a traceback and exit with status 1."""
    try:
        return call()
    except NETWORK_ERRORS as error:
        print(f"{prog}: {network_failure(error)}", file=sys.stderr)
        raise SystemExit(1) from None


def outcome_asset_id(market, outcome) -> str | None:
    """The ID an outcome is priced, ordered and subscribed by: its position ID in a Protocol V2 market, its CTF token ID in a V1 market.
    The market's `version` decides, never which field is filled in (live V1 markets can carry both). None when the version is missing or
    unknown, the ID is missing, or the ID belongs to the other protocol's number range."""
    if outcome is None or market.version not in (ProtocolVersion.V1, ProtocolVersion.V2):
        return None
    v2 = market.version == ProtocolVersion.V2
    asset = outcome.position_id if v2 else outcome.token_id
    asset = "" if asset is None else str(asset).strip()
    return asset if asset and is_v2_position_id(asset) == v2 else None


def yes_no_tokens(market) -> tuple[str, str] | None:
    """(YES asset ID, NO asset ID) for a binary market, else None. See outcome_asset_id (the name is older than Protocol V2)."""
    outcomes = market.outcomes
    if outcomes is None:
        return None
    yes_id, no_id = outcome_asset_id(market, outcomes.yes), outcome_asset_id(market, outcomes.no)
    return (yes_id, no_id) if yes_id and no_id and yes_id != no_id else None


def asks_and_bids(book) -> tuple[list[Level], list[Level]]:
    """(asks best first, bids best first) as float levels."""
    asks = sorted((float(l.price), float(l.size)) for l in book.asks)
    bids = sorted(((float(l.price), float(l.size)) for l in book.bids), reverse=True)
    return asks, bids


async def books_by_token(client: AsyncPublicClient, token_ids: Iterable[str], chunk: int = 50) -> dict[str, object]:
    """Fetch order books for many tokens in batches, keyed by token id."""
    ids = list(dict.fromkeys(token_ids))
    out: dict[str, object] = {}
    for i in range(0, len(ids), chunk):
        for book in await client.get_order_books(token_ids=ids[i:i + chunk]):
            out[str(book.asset_id)] = book
    return out
