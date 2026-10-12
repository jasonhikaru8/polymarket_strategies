"""The Chapter 5 guard, also enforced by the reader toolkit before new orders.

Live trading needs all of: an explicit flag, `POLYMARKET_STRATEGIES_LIVE=1`, no kill-switch file,
and a location that is not geoblocked. A passing guard does not place an order or prove that trading is permitted.
"""
from __future__ import annotations

import json
import math
import os
import urllib.request
from pathlib import Path

GEOBLOCK_URL = "https://polymarket.com/api/geoblock"

DISCLAIMER = ("RISK NOTICE: trading can lose all the money you put in. This software and the book are provided as is. The author is not "
              "responsible for any investment loss or other damage from using them; you use them at your own risk. Nothing here is "
              "investment, legal or tax advice.")


def state_dir() -> Path:
    """One folder per user for the order ledger and the KILL file, so neither depends on the directory a command is run from.

    `POLYMARKET_STRATEGIES_HOME` overrides the default `~/.polymarket-strategies`. A leading `~` is expanded; a relative value is refused,
    because it would name a different folder (a different ledger and a different KILL file) from every folder a command is run in.
    """
    chosen = os.environ.get("POLYMARKET_STRATEGIES_HOME")
    if not chosen:
        return Path.home() / ".polymarket-strategies"
    folder = Path(chosen).expanduser()
    if not folder.is_absolute():
        raise ValueError("POLYMARKET_STRATEGIES_HOME must be an absolute path (a leading ~ is fine): a relative one would give a different "
                         "order ledger and KILL file in every folder you run from")
    return folder


def kill_files() -> list[Path]:
    """The kill-switch files that stop new orders: the per-user file and one in the current folder."""
    return [state_dir() / "KILL", Path("KILL")]


class NotAllowed(RuntimeError):
    pass


# Polymarket's geoblock endpoint and the public Polygon RPC node both answer HTTP 403 to Python's default User-Agent (checked 3 Oct 2026),
# so every live request names this tool.
USER_AGENT = "polymarket-strategies"


def geoblock_status(timeout: float = 5.0) -> dict:
    """Ask Polymarket whether this IP may place orders. Returns {'blocked', 'ip', 'country', 'region'}."""
    request = urllib.request.Request(GEOBLOCK_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
        return json.load(resp)


def require_live(flag: bool, *, kill_file: Path | None = None, blocked: bool | None = None) -> None:
    """Raise unless live trading is explicitly and safely enabled. Checked in order: flag, environment variable, KILL file, geoblock.

    The KILL file stops NEW orders only, and only when this function is called. It is a manual switch (nothing here measures your losses)
    and it does not cancel orders that are already resting. A KILL file in the per-user folder or in the current folder stops new orders;
    `kill_file` checks one chosen file instead.
    """
    if not flag:
        raise NotAllowed("dry run: pass --live to enable live orders")
    if os.environ.get("POLYMARKET_STRATEGIES_LIVE") != "1":
        raise NotAllowed("set POLYMARKET_STRATEGIES_LIVE=1 to enable live orders")
    for path in ([kill_file] if kill_file is not None else kill_files()):
        if os.path.lexists(path):  # a file, a folder or even a broken link counts: any entry named KILL stops new orders
            raise NotAllowed(f"kill switch engaged: delete {path} to resume")
    if blocked is None:
        # fail closed: only an explicit "blocked": false counts as allowed. A missing field, a null or an odd value counts as blocked,
        # and a network or HTTP error raises before we get here.
        blocked = geoblock_status().get("blocked") is not False
    if blocked:
        raise NotAllowed("orders are not allowed from this location (Polymarket geoblock)")


def cap_size(requested_usdc: float, max_usdc: float) -> float:
    """Never exceed the per-order cap. The trading toolkit itself bounds orders with limits.max_cash and limits.max_shares."""
    for value in (requested_usdc, max_usdc):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("sizes must be finite, nonnegative numbers")
    return min(requested_usdc, max_usdc)
