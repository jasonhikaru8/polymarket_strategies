"""wallet_audit.run reads both position books, most recent first, and counts each position once (offline, with a fake client)."""
import asyncio
from types import SimpleNamespace

from polymarket_strategies import wallet_audit


class Pager:
    def __init__(self, items):
        self.items = items

    async def iter_items(self):
        for x in self.items:
            yield x


class FakeClient:
    calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def list_trades(self, **kw):
        return Pager([SimpleNamespace(side="BUY", size=10, price=0.5, event_slug="e1", slug="m1"), SimpleNamespace(side="BUY", size=10, price=0.6, event_slug="e1", slug="m2")])

    def list_positions(self, **kw):
        FakeClient.calls.append(kw)
        book = {"OPEN": [SimpleNamespace(asset_id=1, total_pnl=-40.0), SimpleNamespace(asset_id=2, total_pnl=5.0)], "CLOSED": [SimpleNamespace(asset_id=3, total_pnl=30.0), SimpleNamespace(asset_id=2, total_pnl=5.0)]}
        return Pager(book[kw["status"]])


def test_run_reads_open_and_closed_most_recent_first_and_counts_once(monkeypatch):
    monkeypatch.setattr(wallet_audit, "AsyncPublicClient", FakeClient)
    out = asyncio.run(wallet_audit.run("0xabc", 1000))
    assert [(c["status"], c["sort_by"], c["sort_direction"]) for c in FakeClient.calls] == [("OPEN", "TIMESTAMP", "DESC"), ("CLOSED", "TIMESTAMP", "DESC")]
    assert (out["positions"], out["net_pnl"], out["distinct_events"], out["buy_fills"]) == (3, -5.0, 1, 2)  # asset 2 appears in both books and counts once; the unredeemed loser is included


class RecordingClient(FakeClient):
    trade_calls = []

    def list_trades(self, **kw):
        RecordingClient.trade_calls.append(kw)
        return Pager([SimpleNamespace(side="BUY", size=10, price=0.5, event_slug=f"e{i}", slug="m") for i in range(3)])


def test_the_audit_asks_for_taker_fills_explicitly_and_says_so_in_its_output(monkeypatch):
    RecordingClient.trade_calls = []
    monkeypatch.setattr(wallet_audit, "AsyncPublicClient", RecordingClient)
    out = asyncio.run(wallet_audit.run("0xabc", 1000))
    assert RecordingClient.trade_calls[0]["taker_only"] is True and RecordingClient.trade_calls[0]["full_history"] is True
    assert "taker fills only" in out["scope"] and "unrealized" in out["pnl_basis"]
    assert out["distinct_events"] == 3 and out["positions_in_profit"] == 2


def test_a_wallet_with_exactly_the_limit_of_rows_is_not_called_truncated(monkeypatch):
    monkeypatch.setattr(wallet_audit, "AsyncPublicClient", RecordingClient)
    exact = asyncio.run(wallet_audit.run("0xabc", 3))  # 3 trades, and at most 2 positions per book
    assert exact["truncated_at_limit"] is False and not any("read at most" in f for f in exact["flags"])
    cut = asyncio.run(wallet_audit.run("0xabc", 2))  # a third trade exists, so the read stopped early
    assert cut["truncated_at_limit"] is True and any("read at most 2" in f for f in cut["flags"])


def test_a_limit_below_one_is_refused(capsys):
    import pytest
    with pytest.raises(SystemExit) as failure:
        wallet_audit.main(["0xabc", "--limit", "0"])
    assert failure.value.code == 2 and "at least 1" in capsys.readouterr().err
