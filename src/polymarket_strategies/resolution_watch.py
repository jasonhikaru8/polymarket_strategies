"""B7/B8 Resolution watch: read a market's resolution source, end date and UMA status, or list the markets in dispute right now. Read-only.

The rules define the outcome, not the title. Check the named source, end date and status history.
The settlement estimate (`expected_settlement_time`) is read from the Data API's raw response because the SDK's `Resolution` type does not carry it yet. It is an estimate, not a deadline.
`was_disputed` is reported as supplied by the API; it is not a substitute for the market's status history.
Some markets list every status twice ([proposed, proposed, disputed, disputed]), so disputes are counted after collapsing consecutive repeats.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import sys
import urllib.request

from polymarket import AsyncPublicClient

from .data import run_public
from .safety import USER_AGENT

DATA_API = "https://data-api.polymarket.com/v2/resolutions"
GAMMA = "https://gamma-api.polymarket.com/markets/keyset"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310  (a fixed public https endpoint)
        return json.load(r)


def dispute_count(history: list[str]) -> int:
    """Disputes in an oracle status history, each step counted once. A real sequence alternates (a dispute follows a proposal),
    but some markets list every status twice, so ["proposed", "proposed", "disputed", "disputed"] is one dispute, not two."""
    return [status for status, _ in itertools.groupby(history)].count("disputed")


def settlement_estimates(condition_ids: list[str]) -> dict[str, dict]:
    """condition id -> {expected_settlement_time, settlement_time_basis, extended_review} from the Data API's raw rows (at most 20 ids a call)."""
    out: dict[str, dict] = {}
    for i in range(0, len(condition_ids), 20):
        for row in _get(f"{DATA_API}?condition=" + ",".join(condition_ids[i:i + 20]))["data"]:
            out[row["condition_id"]] = {k: row.get(k) for k in ("expected_settlement_time", "settlement_time_basis", "extended_review")}
    return out


def disputed_now(limit: int = 100) -> list[dict]:
    """Open markets whose oracle status is 'disputed', biggest first, with the number of disputes so far (repeated entries counted once;
    two or more means the token vote) and the settlement estimate if there is one."""
    page = _get(f"{GAMMA}?closed=false&uma_resolution_status=disputed&limit={min(limit, 100)}")["markets"]
    estimates = settlement_estimates([m["conditionId"] for m in page])
    rows = []
    for m in page:
        history = json.loads(m.get("umaResolutionStatuses") or "[]")
        prices = json.loads(m.get("outcomePrices") or "[]")
        rows.append({"question": m["question"].strip(), "disputes": dispute_count(history), "volume": round(float(m.get("volume") or 0)), "yes_price": float(prices[0]) if prices else None,
                     "end_date": m.get("endDate"), **estimates.get(m["conditionId"], {})})
    return sorted(rows, key=lambda r: -r["volume"])


async def run(slugs: list[str]) -> list[dict]:
    rows: list[dict] = []
    async with AsyncPublicClient() as client:
        # the SDK leaves out closed markets unless asked, so look at both open and resolved ones
        markets = [m for closed in (False, True) for i in range(0, len(slugs), 100)  # the API returns at most 100 markets a call
                   for m in (await client.list_markets(slug=slugs[i:i + 100], closed=closed, page_size=100).first_page()).items]
        by_condition = {str(m.condition_id): m for m in markets if m.condition_id}
        condition_ids = list(by_condition)
        resolutions = []
        for i in range(0, len(condition_ids), 20):
            resolutions.extend(await client.get_resolutions(condition_ids=condition_ids[i:i + 20]))
        details = {str(r.condition_id): r for r in resolutions}
        estimates = settlement_estimates(list(by_condition)) if by_condition else {}
        for cid, m in by_condition.items():
            r = details.get(cid)
            rows.append({
                "slug": m.slug, "question": m.question, "end_date": str(m.state.end_date),
                "uma_status": m.resolution.uma_resolution_status, "source": m.resolution.source or "(none stated)",
                "status": str(r.status) if r else None, "was_disputed": r.was_disputed if r else None,
                "extended_review": r.extended_review if r else None,
                "resolved_at": str(r.resolved_at) if r and r.resolved_at else None,
                "expected_settlement_time": estimates.get(cid, {}).get("expected_settlement_time"),
                "settlement_time_basis": estimates.get(cid, {}).get("settlement_time_basis"),
            })
    found = {row["slug"] for row in rows}
    rows.extend({"slug": slug, "error": "no open or resolved market with this slug"} for slug in dict.fromkeys(slugs) if slug not in found)
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="polymarket-strategies resolution-watch", description=__doc__.splitlines()[0])
    ap.add_argument("slugs", nargs="*", help="market slugs")
    ap.add_argument("--disputed", action="store_true", help="list the open markets in dispute right now instead")
    args = ap.parse_args(argv)
    if args.disputed:
        rows = run_public("resolution-watch", disputed_now)
        if len(rows) >= 100:
            print("One call returns at most 100 markets: there may be more disputed markets than the 100 listed, and the order is by volume within these 100.", file=sys.stderr)
        print(json.dumps(rows, indent=2))
    elif args.slugs:
        print(json.dumps(run_public("resolution-watch", lambda: asyncio.run(run(args.slugs))), indent=2))
    else:
        ap.error("give one or more market slugs, or --disputed")
