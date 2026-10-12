"""Offline strategy-to-order workflows using real previews and decision checks."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from types import SimpleNamespace as NS

from polymarket import AcceptedOrder, AsyncSecureClient, BalanceAllowance, PRODUCTION
from polymarket.models.clob.account import ClobTrade, OpenOrder
from polymarket.models.clob.orders import SignedOrder
from polymarket._internal.actions.orders.context import resolve_order_exchange_address
from polymarket._internal.environment import get_environment_config
from polymarket.pagination import AsyncPaginator, Page
import pytest

from polymarket_strategies import execution, order_store, safety, trade_plan

NOW = 1_800_000_000
TOKEN = str(1 << 40)
CONDITION = "0x" + "c" * 64
ORDER_ID = "0x" + "b" * 64
WALLET = "0x" + "a" * 40
TRADE_ID = "11111111-1111-4111-8111-111111111111"
SOURCE = "https://example.invalid/synthetic-report"
DEFINITION = "The synthetic public report includes the exact reviewed term."
SIGNATURE = "OFFLINE_FAKE_SIGNATURE_MUST_NOT_BE_STORED"


class SyntheticClient:
    """A combined public/authenticated surface; every response is local synthetic data."""
    wallet = WALLET

    def __init__(self, kind):
        self.calls = []
        self.order = None
        self.market = NS(
            slug="synthetic-workflow", condition_id=CONDITION, question="Synthetic report question?",
            description=DEFINITION, version="v1", resolution=NS(source=SOURCE, uma_resolution_status=None),
            state=NS(active=True, closed=False, archived=False, accepting_orders=True,
                     enable_order_book=True, neg_risk=False,
                     end_date=datetime.fromtimestamp(NOW + 10 * 86400, timezone.utc)),
            outcomes=NS(yes=NS(token_id=TOKEN, label="Yes"), no=NS(token_id=str(int(TOKEN) + 1), label="No")),
            trading=NS(fees_enabled=True, fee_schedule=NS(rate=0.04, exponent=1,
                                                        rebate_rate=0, taker_only=True)))
        price = Decimal("0.90") if kind == "favorite_carry" else Decimal("0.50")
        self.book = NS(asset_id=TOKEN, condition_id=CONDITION, neg_risk=False,
                       timestamp=datetime.fromtimestamp(NOW, timezone.utc), tick_size=Decimal("0.01"),
                       min_order_size=Decimal("5"), asks=[NS(price=price, size=Decimal("20"))],
                       bids=[NS(price=price - Decimal("0.01"), size=Decimal("20"))])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def list_markets(self, **kwargs):
        self.calls.append("public_markets")
        assert kwargs["slug"] == [self.market.slug]

        async def fetch(cursor):
            return Page((self.market,), has_more=False, next_cursor=None)
        return AsyncPaginator(fetch)

    async def get_order_book(self, **kwargs):
        self.calls.append("public_book")
        assert kwargs["token_id"] == self.book.asset_id
        return self.book

    async def get_balance_allowance(self, **kwargs):
        self.calls.append("balance")
        exchange = resolve_order_exchange_address(get_environment_config(PRODUCTION), asset_id=self.book.asset_id, neg_risk=False)
        if kwargs["asset_type"] == "COLLATERAL":
            balance = 20_000_000
        else:
            # A taker BUY pays its fee in pUSD on top of the price and receives every matched share.
            balance = int(Decimal(self.order["size"]) * 1_000_000)
        return BalanceAllowance(balance=balance, allowances={str(exchange): balance})

    async def create_limit_order(self, **kwargs):
        self.calls.append("sign")
        self.order = kwargs
        return SignedOrder(builder="0x" + "0" * 64, expiration=kwargs["expiration"], maker=WALLET,
            maker_amount=int(Decimal(kwargs["size"]) * Decimal(kwargs["price"]) * 1_000_000),
            metadata="0x" + "0" * 64, order_type="GTD", salt=1, side=kwargs["side"],
            signature=SIGNATURE, signature_type=0, signer=WALLET,
            taker_amount=int(Decimal(kwargs["size"]) * 1_000_000), timestamp=NOW,
            token_id=kwargs["token_id"], post_only=kwargs["post_only"])

    async def post_order(self, signed):
        self.calls.append("post")
        assert signed.order_type == "GTD" and signed.side == "BUY"
        return AcceptedOrder(order_id=ORDER_ID, status="matched", making_amount=0, taking_amount=0,
                             trade_ids=(TRADE_ID,), transactions_hashes=())

    async def get_order(self, **kwargs):
        self.calls.append("get_order")
        assert kwargs["order_id"] == ORDER_ID
        return OpenOrder(id=ORDER_ID, market=CONDITION, asset_id=self.book.asset_id, owner="offline-owner",
            maker_address=WALLET, side="BUY", price=self.order["price"], original_size="5",
            size_matched="5", outcome="Yes", order_type="GTD", status="MATCHED",
            associate_trades=(TRADE_ID,), created_at=datetime.now(timezone.utc),
            expiration=self.order["expiration"])

    def list_account_trades(self, **kwargs):
        self.calls.append("account_trades")
        assert kwargs["market"] == CONDITION
        fill = ClobTrade(id=TRADE_ID, market=CONDITION, asset_id=self.book.asset_id, owner="offline-owner",
            maker_address=WALLET, taker_order_id=ORDER_ID, side="BUY", trader_side="TAKER",
            price=self.order["price"], size="5", outcome="Yes", status="CONFIRMED", fee_rate_bps="0",
            bucket_index=0, transaction_hash="0x" + "e" * 64, maker_orders=(),
            match_time=datetime.now(timezone.utc), last_update=datetime.now(timezone.utc))

        async def fetch(cursor):
            return Page((fill,), has_more=False, next_cursor=None)
        return AsyncPaginator(fetch)


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # the real guard's relative KILL path is isolated
    monkeypatch.setenv("POLYMARKET_STRATEGIES_LIVE", "1")
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", WALLET)
    for name in ("POLYMARKET_SIGNER_PRIVATE_KEY", "POLYMARKET_API_KEY",
                 "POLYMARKET_API_SECRET", "POLYMARKET_API_PASSPHRASE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(trade_plan, "time", NS(time=lambda: NOW))
    monkeypatch.setattr(safety, "geoblock_status", lambda: {"blocked": False})
    monkeypatch.setattr(execution.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("An external request was attempted"))

    async def forbidden_auth(**kwargs):
        pytest.fail("Real authentication was attempted")
    monkeypatch.setattr(AsyncSecureClient, "create", forbidden_auth)
    return monkeypatch, tmp_path / "orders.sqlite3"


async def configuration(client, kind):
    inspected = await trade_plan.inspect(client.market.slug, client)
    config = trade_plan.draft_config(inspected, kind=kind, now=NOW)
    config.update(limit_price=str(client.book.asks[0].price))
    config["limits"].update(max_cash="10", max_shares="5")
    config["approval"].update(approved=True, yes_definition=DEFINITION, note="Synthetic full rules reviewed.")
    common = {"target_yes_definition": DEFINITION, "resolution_source": SOURCE,
              "evidence": "Synthetic evidence for offline integration only.", "source_notes": "No real forecast or data."}
    if kind == "mention_base_rate":
        inputs = common | {"cohort": "synthetic-independent-reports", "comparability_reviewed": True,
            "min_events": 20, "events": [
                {"event_id": f"event-{i}", "group": f"independent-{i}", "outcome_yes": i < 18,
                 "resolved_at": NOW - 86400 * (i + 1), "cohort": "synthetic-independent-reports",
                 "resolution_source": SOURCE, "yes_definition": DEFINITION} for i in range(20)]}
    else:
        favorite = kind == "favorite_carry"
        inputs = common | {"probability_yes": 0.98 if favorite else 0.75,
            "conservative_low_yes": 0.96 if favorite else 0.65,
            "conservative_high_yes": 0.995 if favorite else 0.85,
            "as_of": NOW, "valid_until": NOW + 1800}
        if favorite:
            inputs.update(min_favorite_price=0.85, min_expected_annual_return=0.1, max_days=14)
    config["strategy"]["inputs"] = inputs
    return config


@pytest.mark.parametrize("kind", ["model_value", "favorite_carry", "mention_base_rate"])
def test_actual_strategy_preview_submission_and_confirmed_ledger_flow(offline, kind):
    monkeypatch, ledger = offline
    client = SyntheticClient(kind)
    monkeypatch.setattr(trade_plan, "AsyncPublicClient", lambda: client)

    async def workflow():
        config = await configuration(client, kind)
        preview = await trade_plan.preview(config)
        assert preview["eligible"] and preview["decision"]["eligible"]
        assert preview["decision"]["probability"] == pytest.approx(0.98 if kind == "favorite_carry" else 0.9 if kind == "mention_base_rate" else 0.75)
        assert preview["decision"]["edge_per_share"] >= config["strategy"]["min_edge"]
        assert Decimal(preview["cash_bound"]) <= Decimal(config["limits"]["max_cash"])
        submitted = await execution.submit(config, ledger, confirm=preview["plan_id"], live=True, client=client)
        assert submitted["phase"] == "ACCEPTED" and submitted["filled_shares"] == "not yet reconciled"
        reconciled = await execution.status(config["intent_id"], ledger, client=client)
        assert reconciled["trades_complete"] and reconciled["confirmed_filled_shares"] == "5"
        assert reconciled["pending_filled_shares"] == "0" and reconciled["remaining_open_shares"] == "0"
        assert Decimal(reconciled["current_outcome_holdings"]) == Decimal(reconciled["confirmed_filled_shares"]) == Decimal("5")
        fills = order_store.fills(ledger, config["intent_id"])
        assert len(fills) == 1 and fills[0]["status"] == "CONFIRMED" and fills[0]["size"] == "5"
    asyncio.run(workflow())
    assert client.calls.count("sign") == 1 and client.calls.count("post") == 1
    assert client.calls.count("public_book") == 3  # preview, submit, and the post-sign refresh
    assert SIGNATURE not in json.dumps(execution.local_summary(ledger)) and SIGNATURE.encode() not in ledger.read_bytes()


def test_expired_forecast_rejects_actual_preview_and_never_posts(offline):
    monkeypatch, ledger = offline
    client = SyntheticClient("model_value")
    monkeypatch.setattr(trade_plan, "AsyncPublicClient", lambda: client)

    async def workflow():
        config = await configuration(client, "model_value")
        config["strategy"]["inputs"].update(as_of=NOW - 3600, valid_until=NOW - 1)
        preview = await trade_plan.preview(config)
        assert not preview["eligible"] and any("forecast expires" in reason for reason in preview["reasons"])
        with pytest.raises(execution.ExecutionError, match="eligible fresh preview"):
            await execution.submit(config, ledger, confirm=preview["plan_id"], live=True, client=client)
    asyncio.run(workflow())
    assert "sign" not in client.calls and "post" not in client.calls and not ledger.exists()
