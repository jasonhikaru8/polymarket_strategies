"""resolution-watch reads the settlement estimate from the raw Data API rows and lists disputed markets; both are tested offline with canned responses."""
import json
from types import SimpleNamespace as NS

import pytest

from polymarket_strategies import resolution_watch as rw

MARKETS = {"markets": [
    {"conditionId": "0xa", "question": " Will it happen? ", "umaResolutionStatuses": json.dumps(["proposed", "disputed", "proposed", "disputed"]), "volume": "250000.5", "outcomePrices": '["0.095", "0.905"]', "endDate": "2027-01-01T00:00:00Z"},
    {"conditionId": "0xb", "question": "Small one", "umaResolutionStatuses": json.dumps(["proposed", "disputed"]), "volume": "12", "outcomePrices": '["0.5", "0.5"]', "endDate": None},
    {"conditionId": "0xc", "question": "Big one", "umaResolutionStatuses": json.dumps(["proposed", "disputed"]), "volume": "9000000", "outcomePrices": '["0.02", "0.98"]', "endDate": None},
]}
ROWS = {"data": [
    {"condition_id": "0xa", "expected_settlement_time": "2026-10-02T00:00:00Z", "settlement_time_basis": "dvm_round_estimate", "extended_review": False, "status": "disputed"},
    {"condition_id": "0xb", "extended_review": False, "status": "disputed"},  # no estimate: the fields are left out
]}


def fake_get(url):
    return MARKETS if url.startswith(rw.GAMMA) else ROWS


def test_disputed_now_lists_biggest_first_with_counts_and_estimates(monkeypatch):
    monkeypatch.setattr(rw, "_get", fake_get)
    rows = rw.disputed_now()
    assert [r["question"] for r in rows] == ["Big one", "Will it happen?", "Small one"]  # biggest volume first, whitespace trimmed
    by = {r["question"]: r for r in rows}
    assert by["Will it happen?"]["disputes"] == 2 and by["Small one"]["disputes"] == 1  # two disputes: the token vote
    assert by["Will it happen?"]["expected_settlement_time"] == "2026-10-02T00:00:00Z" and by["Will it happen?"]["settlement_time_basis"] == "dvm_round_estimate"
    assert by["Small one"]["expected_settlement_time"] is None and by["Big one"].get("expected_settlement_time") is None
    assert by["Will it happen?"]["yes_price"] == 0.095 and by["Will it happen?"]["volume"] == 250000


@pytest.mark.parametrize("history,disputes", [
    (["proposed", "proposed", "disputed", "disputed"], 1),  # every status listed twice: one dispute, no token vote
    (["proposed", "proposed", "disputed", "disputed", "proposed", "proposed", "disputed", "disputed"], 2),
    (["proposed", "disputed", "proposed", "disputed"], 2),
    (["proposed", "proposed", "disputed", "disputed", "proposed", "proposed"], 1),  # Amsterdam's history in Chapter 14's log
    (["proposed", "proposed"], 0), ([], 0)])
def test_disputes_are_counted_once_each_when_a_market_lists_every_status_twice(history, disputes):
    assert rw.dispute_count(history) == disputes


def test_the_disputed_list_counts_a_doubled_history_as_one_dispute(monkeypatch):
    page = {"markets": [{"conditionId": "0xd", "question": "Doubled", "umaResolutionStatuses": json.dumps(["proposed", "proposed", "disputed", "disputed"]),
                         "volume": "5", "outcomePrices": '["0.5", "0.5"]', "endDate": None}]}
    monkeypatch.setattr(rw, "_get", lambda url: page if url.startswith(rw.GAMMA) else {"data": []})
    assert rw.disputed_now()[0]["disputes"] == 1


def test_settlement_estimates_asks_twenty_conditions_at_a_time(monkeypatch):
    urls = []
    monkeypatch.setattr(rw, "_get", lambda url: urls.append(url) or {"data": []})
    rw.settlement_estimates([f"0x{i:02x}" for i in range(45)])
    assert len(urls) == 3 and urls[0].count(",") == 19 and urls[2].count(",") == 4


def test_resolution_reader_batches_sdk_calls_and_preserves_every_market(monkeypatch):
    import asyncio

    calls = []
    markets = [NS(condition_id=f"0x{i:064x}", slug=f"market-{i}", question=f"Question {i}",
                  state=NS(end_date=None), resolution=NS(uma_resolution_status="proposed", source="source"))
               for i in range(45)]
    missing_id = NS(condition_id=None)

    class Pages:
        def __init__(self, items):
            self.items = items

        async def first_page(self):
            return NS(items=self.items)

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def list_markets(self, **kwargs):
            return Pages([markets[-1]] if kwargs["closed"] else [*markets, missing_id])

        async def get_resolutions(self, *, condition_ids):
            calls.append(condition_ids)
            assert len(condition_ids) <= 20
            return [NS(condition_id=cid, status="proposed", was_disputed=False,
                       extended_review=False, resolved_at=None) for cid in condition_ids]

    monkeypatch.setattr(rw, "AsyncPublicClient", Client)
    monkeypatch.setattr(rw, "settlement_estimates", lambda ids: {
        cid: {"expected_settlement_time": "estimate", "settlement_time_basis": "basis"} for cid in ids})
    rows = asyncio.run(rw.run([m.slug for m in markets]))
    assert [len(ids) for ids in calls] == [20, 20, 5]
    assert [cid for ids in calls for cid in ids] == [m.condition_id for m in markets]
    assert len(rows) == 45 and rows[-1]["slug"] == "market-44"
    assert all(row["status"] == "proposed" and row["expected_settlement_time"] == "estimate" for row in rows)


def test_a_slug_that_matches_no_market_gets_its_own_row_instead_of_vanishing(monkeypatch):
    import asyncio

    known = NS(condition_id="0x" + "1" * 64, slug="known", question="Known?", state=NS(end_date=None),
               resolution=NS(uma_resolution_status="proposed", source="source"))

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def list_markets(self, **kwargs):
            items = [] if kwargs["closed"] else [known]

            async def first_page():
                return NS(items=items)
            return NS(first_page=first_page)

        async def get_resolutions(self, *, condition_ids):
            return []

    monkeypatch.setattr(rw, "AsyncPublicClient", Client)
    monkeypatch.setattr(rw, "settlement_estimates", lambda ids: {})
    rows = asyncio.run(rw.run(["known", "typo-slug", "typo-slug"]))
    assert [r["slug"] for r in rows] == ["known", "typo-slug"]
    assert "no open or resolved market" in rows[1]["error"]


def test_a_full_page_of_disputes_says_it_may_not_be_all_of_them(monkeypatch, capsys):
    page = {"markets": [{"conditionId": f"0x{i}", "question": f"Q{i}", "umaResolutionStatuses": '["disputed"]', "volume": str(i),
                         "outcomePrices": '["0.5","0.5"]', "endDate": None} for i in range(100)]}
    monkeypatch.setattr(rw, "_get", lambda url: page if url.startswith(rw.GAMMA) else {"data": []})
    rw.main(["--disputed"])
    assert "at most 100" in capsys.readouterr().err


def test_more_than_one_hundred_slugs_are_looked_up_in_batches_and_none_is_called_missing(monkeypatch):
    import asyncio
    markets = {f"market-{i}": NS(condition_id=f"0x{i:064x}", slug=f"market-{i}", question=f"Q{i}", state=NS(end_date=None),
                                 resolution=NS(uma_resolution_status="proposed", source="source")) for i in range(130)}
    asked = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def list_markets(self, **kwargs):
            asked.append(len(kwargs["slug"]))
            found = [] if kwargs["closed"] else [markets[s] for s in kwargs["slug"]]

            async def first_page():
                assert len(kwargs["slug"]) <= 100
                return NS(items=found)
            return NS(first_page=first_page)

        async def get_resolutions(self, *, condition_ids):
            return []
    monkeypatch.setattr(rw, "AsyncPublicClient", Client)
    monkeypatch.setattr(rw, "settlement_estimates", lambda ids: {})
    rows = asyncio.run(rw.run(list(markets)))
    assert len(rows) == 130 and not any("error" in row for row in rows) and 100 in asked and 30 in asked
