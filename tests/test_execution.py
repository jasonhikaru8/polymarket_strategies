"""Order lifecycle on injected clients. No credentials or requests reach an external service."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace as NS
from uuid import uuid4

from eth_account import Account
from polymarket import AcceptedOrder, BalanceAllowance, PRODUCTION
from polymarket.errors import RateLimitError, RequestRejectedError, TransportError
from polymarket.models.clob.order_response import RawOrderResponse, RejectedOrder, normalize_order_response
from polymarket._internal.actions.orders.context import resolve_order_exchange_address
from polymarket._internal.environment import get_environment_config
from polymarket.pagination import AsyncPaginator, Page
import pytest

from polymarket_strategies import execution as ex, order_store

WALLET = "0x" + "a" * 40
ORDER_ID = "0x" + "b" * 64
CONDITION = "0x" + "c" * 64
TOKEN = str(1 << 40)  # the SDK identifies this synthetic token as protocol v1
SECRET = "SECRET_MUST_NOT_BE_OUTPUT"


def plan(config):
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    side = config.get("side", "BUY")
    return {"plan_id": digest[:16], "config_hash": digest, "intent_id": config["intent_id"],
            "contract_fingerprint": "d" * 64, "eligible": True,
            "cash_bound": "5.10001" if side == "BUY" else "0", "fee_bound": "0.10001",
            "order": {"token_id": config.get("token_id", TOKEN), "condition_id": CONDITION,
                      "side": side, "size": "10", "price": "0.50", "expiration": 2_000_000_000,
                      "post_only": False, "neg_risk": False, "version": config.get("version", "v1"),
                      "fee_schedule": {"rate": 0.04, "exponent": 1, "rebate_rate": 0.25, "taker_only": True}},
            "quote": {"tick_size": "0.01", "min_order_size": "5", "best_ask": "0.5"}}


class Client:
    wallet = WALLET

    def __init__(self, config):
        self.config = config
        self.calls = []
        self.pages = [[]]
        self.post_failure = None
        self.cancel_failure = None
        self.get_failure = None
        self.order_status = "LIVE"
        self.allow_wrong_exchange = False
        self.paging_failure = False
        self.matched = "0"
        self.associate_trades = ()
        self.remote_changes = {}
        self.post_response = None
        self.open_orders = []

    async def close(self):
        self.calls.append("close")

    async def get_balance_allowance(self, **kwargs):
        self.calls.append(("balance", kwargs))
        exchange = resolve_order_exchange_address(get_environment_config(PRODUCTION),
            asset_id=self.config.get("token_id", TOKEN), neg_risk=False)
        if self.allow_wrong_exchange:
            exchange = "0x" + "f" * 40
        return BalanceAllowance(balance=20_000_000, allowances={str(exchange): 20_000_000})

    async def create_limit_order(self, **kwargs):
        self.calls.append("sign")
        quantity, notional = int(Decimal(kwargs["size"]) * 1_000_000), int(Decimal(kwargs["size"]) * Decimal(kwargs["price"]) * 1_000_000)
        maker, taker = (notional, quantity) if kwargs["side"] == "BUY" else (quantity, notional)
        return NS(maker=self.wallet, token_id=kwargs["token_id"], side=kwargs["side"], maker_amount=maker,
                  taker_amount=taker, expiration=kwargs["expiration"], post_only=kwargs["post_only"], signature=SECRET,
                  order_type="GTD" if kwargs["expiration"] else "GTC", builder="0x" + "0" * 64)

    async def post_order(self, signed):
        self.calls.append("post")
        if self.post_failure:
            raise self.post_failure
        if self.post_response is not None:
            return self.post_response
        return AcceptedOrder(order_id=ORDER_ID, status="live", making_amount=0, taking_amount=0,
                             trade_ids=(), transactions_hashes=())

    def list_open_orders(self, **kwargs):
        self.calls.append(("open_orders", kwargs))

        async def fetch(cursor):
            return Page(tuple(self.open_orders), has_more=False, next_cursor=None)
        return AsyncPaginator(fetch)

    async def get_order(self, **kwargs):
        self.calls.append("get_order")
        if self.get_failure:
            raise self.get_failure
        fields = dict(id=kwargs["order_id"], maker_address=self.wallet, asset_id=self.config.get("token_id", TOKEN),
                  condition_id=CONDITION, side=self.config.get("side", "BUY"), original_size=Decimal("10"),
                  price=Decimal("0.5"), created_at=datetime.now(timezone.utc), status=self.order_status,
                  order_type="GTD", expires_at=datetime.fromtimestamp(2_000_000_000, timezone.utc),
                  size_matched=Decimal(self.matched), associate_trades=self.associate_trades)
        return NS(**(fields | self.remote_changes))

    def list_account_trades(self, **kwargs):
        self.calls.append(("trades", kwargs))

        async def fetch(cursor):
            index = int(cursor or 0)
            if self.paging_failure and index:
                raise RuntimeError(SECRET)
            more = index + 1 < len(self.pages)
            return Page(tuple(self.pages[index]), has_more=more, next_cursor=str(index + 1) if more else None)
        return AsyncPaginator(fetch)

    async def cancel_order(self, **kwargs):
        self.calls.append("cancel")
        if self.cancel_failure:
            raise self.cancel_failure
        self.order_status = "CANCELED"
        return NS(canceled=(ORDER_ID,))


def trade(identifier="a1", *, role="TAKER", state="CONFIRMED", size="2", updated=None):
    maker = NS(order_id=ORDER_ID, asset_id=TOKEN, maker_address=WALLET, side="BUY",
               price=Decimal("0.5"), matched_amount=Decimal(size))
    return NS(id=identifier, taker_order_id=ORDER_ID if role == "TAKER" else "other-order",
              condition_id=CONDITION, asset_id=TOKEN if role == "TAKER" else "another-outcome",
              maker_address=WALLET if role == "TAKER" else "another-wallet", side="BUY",
              price=Decimal("0.5"), size=Decimal(size if role == "TAKER" else "100"),
              status=state, maker_orders=(maker,) if role == "MAKER" else (),
              updated_at=updated or datetime.now(timezone.utc))


@pytest.fixture
def setup(monkeypatch, tmp_path):
    config = {"intent_id": str(uuid4()), "approval": {"note": SECRET}}
    client = Client(config)
    ledger = tmp_path / "orders.sqlite3"
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", WALLET)
    for name in ("POLYMARKET_SIGNER_PRIVATE_KEY", "POLYMARKET_API_KEY", "POLYMARKET_API_SECRET", "POLYMARKET_API_PASSPHRASE"):
        monkeypatch.setenv(name, SECRET)

    async def preview(config, client=None):
        return plan(config)
    monkeypatch.setattr(ex, "_preview", preview)
    monkeypatch.setattr(ex.safety, "require_live", lambda live: client.calls.append("guard") if live else (_ for _ in ()).throw(ex.safety.NotAllowed("disabled")))
    monkeypatch.setattr(ex.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("external request forbidden")))
    return config, client, ledger


def submit(config, client, ledger):
    return asyncio.run(ex.submit(config, ledger, confirm=plan(config)["plan_id"], live=True, client=client))


def test_submit_guards_rechecks_and_persists_only_economic_data(setup):
    config, client, ledger = setup
    result = submit(config, client, ledger)
    assert result["phase"] == "ACCEPTED" and result["filled_shares"] == "not yet reconciled"
    assert client.calls[0] == "guard" and client.calls[-2:] == ["guard", "post"]
    assert client.calls.count("sign") == 1 and client.calls.count("post") == 1
    stored = ex.local_summary(ledger)
    assert SECRET not in json.dumps(stored) and SECRET.encode() not in ledger.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        submit(config, client, ledger)
    assert client.calls.count("post") == 1


@pytest.mark.parametrize("change", ["tick_size", "fee_schedule", "eligibility"])
def test_post_sign_market_change_aborts_before_post(setup, monkeypatch, change):
    config, client, ledger = setup
    count = 0

    async def preview(config, client=None):
        nonlocal count
        count += 1
        result = plan(config)
        if count == 2:
            if change == "tick_size":
                result["quote"]["tick_size"] = "0.001"
            elif change == "fee_schedule":
                result["order"]["fee_schedule"]["rate"] = 0.05
            else:
                result["eligible"] = False
        return result
    monkeypatch.setattr(ex, "_preview", preview)
    with pytest.raises(ex.ExecutionError):
        submit(config, client, ledger)
    assert "post" not in client.calls
    assert order_store.get(ledger, config["intent_id"])["phase"] == "ABORTED"


def test_wrong_exchange_allowance_does_not_authorize_order(setup):
    config, client, ledger = setup
    client.allow_wrong_exchange = True
    with pytest.raises(ex.ExecutionError):
        submit(config, client, ledger)
    assert "sign" not in client.calls and "post" not in client.calls


@pytest.mark.parametrize("error", [TimeoutError(SECRET), asyncio.CancelledError(SECRET), KeyboardInterrupt(SECRET)])
def test_ambiguous_submit_survives_restart_and_blocks_new_intent(setup, error):
    config, client, ledger = setup
    client.post_failure = error
    if isinstance(error, Exception):
        result = submit(config, client, ledger)
        assert SECRET not in json.dumps(result)
    else:
        with pytest.raises(type(error)):
            submit(config, client, ledger)
    assert order_store.get(ledger, config["intent_id"])["phase"] == "UNKNOWN"
    different = {**config, "intent_id": str(uuid4())}
    with pytest.raises(ValueError, match="unresolved intent"):
        submit(different, Client(different), ledger)
    assert client.calls.count("post") == 1


def sdk_response(status, *, success=True, order_id=ORDER_ID, error=""):
    """What the real SDK makes of a POST /order body."""
    return normalize_order_response(RawOrderResponse.model_validate({
        "errorMsg": error, "makingAmount": "0", "orderID": order_id, "status": status, "success": success,
        "takingAmount": "0", "tradeIDs": [], "transactionsHashes": []}))


def open_order(**changes):
    fields = dict(id=ORDER_ID, maker_address=WALLET, asset_id=TOKEN, condition_id=CONDITION, side="BUY",
                  original_size=Decimal("10"), price=Decimal("0.5"), created_at=datetime.now(timezone.utc), status="LIVE",
                  order_type="GTD", expires_at=datetime.fromtimestamp(2_000_000_000, timezone.utc),
                  size_matched=Decimal("0"), associate_trades=())
    return NS(**(fields | changes))


def another_intent():
    config = {"intent_id": str(uuid4()), "approval": {"note": SECRET}}
    return config, Client(config)


@pytest.mark.parametrize("code", ["not_enough_balance", "post_only_would_cross", "invalid_expiration", "market_not_ready"])
def test_definitive_response_codes_are_final_and_messages_are_not_saved(setup, code):
    config, client, ledger = setup
    client.post_response = RejectedOrder(code=code, message=SECRET)
    result = submit(config, client, ledger)
    assert result["phase"] == "REJECTED" and SECRET not in json.dumps(result)
    assert SECRET not in json.dumps(ex.local_summary(ledger))
    other, other_client = another_intent()
    assert submit(other, other_client, ledger)["phase"] == "ACCEPTED"  # a proven refusal does not block the account


def test_unmatched_placement_is_uncertain_and_blocks_the_account(setup):
    config, client, ledger = setup
    response = sdk_response("unmatched")
    assert response.ok is False and response.code == "unmatched"  # the SDK hides the order ID of an order that was placed
    client.post_response = response
    result = submit(config, client, ledger)
    assert result["phase"] == "UNKNOWN" and "placed" in result["error"] and "recover" in result["error"]
    other, other_client = another_intent()
    with pytest.raises(Exception, match="unresolved intent"):
        submit(other, other_client, ledger)


def test_unclassified_failure_response_is_uncertain(setup):
    config, client, ledger = setup
    client.post_response = sdk_response("", success=False, order_id="", error="something new")
    assert client.post_response.code == "unknown"
    assert submit(config, client, ledger)["phase"] == "UNKNOWN"


@pytest.mark.parametrize("failure,phase", [
    (RequestRejectedError("m", status=425, restriction="restarting"), "REJECTED"), (RequestRejectedError("m", status=503), "REJECTED"),
    (RequestRejectedError("m", status=400), "REJECTED"), (RateLimitError("m"), "REJECTED"),
    (RequestRejectedError("m", status=500), "UNKNOWN"), (RequestRejectedError("m", status=504), "UNKNOWN"),
    (TransportError("timed out"), "UNKNOWN")])
def test_only_proven_refusals_unblock_the_account(setup, failure, phase):
    config, client, ledger = setup
    client.post_failure = failure
    result = submit(config, client, ledger)
    assert result["phase"] == phase and SECRET not in json.dumps(result)
    other, other_client = another_intent()
    if phase == "REJECTED":
        assert submit(other, other_client, ledger)["phase"] == "ACCEPTED"
    else:
        with pytest.raises(Exception, match="unresolved intent"):
            submit(other, other_client, ledger)


def test_accepted_order_id_is_not_lost_when_the_ledger_write_fails(setup, monkeypatch):
    config, client, ledger = setup
    real = order_store.transition

    def flaky(path, intent_id, phase, **kwargs):
        if phase in {"ACCEPTED", "UNKNOWN"}:
            raise RuntimeError("database is locked")
        return real(path, intent_id, phase, **kwargs)
    monkeypatch.setattr(order_store, "transition", flaky)
    with pytest.raises(ex.ExecutionError, match=ORDER_ID):
        submit(config, client, ledger)


def test_recover_finds_the_single_matching_open_order_after_a_hidden_id(setup):
    config, client, ledger = setup
    client.post_response = sdk_response("unmatched")
    submit(config, client, ledger)
    client.open_orders = [open_order(), open_order(id="0x" + "d" * 64, price=Decimal("0.4"))]
    result = asyncio.run(ex.recover(config["intent_id"], None, ledger, client=client))
    assert result["ok"] is True and result["phase"] == "ACCEPTED" and result["order_id"] == ORDER_ID


def test_recover_without_a_matching_order_points_to_resolve(setup):
    config, client, ledger = setup
    client.post_response = sdk_response("unmatched")
    submit(config, client, ledger)
    result = asyncio.run(ex.recover(config["intent_id"], None, ledger, client=client))
    assert result["ok"] is False and "trade resolve" in result["error"] and result["phase"] == "UNKNOWN"


def test_resolve_waits_for_expiry_and_needs_no_open_order_and_no_fill(setup):
    config, client, ledger = setup
    client.post_response = sdk_response("unmatched")
    submit(config, client, ledger)
    intent = config["intent_id"]
    with pytest.raises(ex.ExecutionError, match="confirmation"):
        asyncio.run(ex.resolve(intent, ledger, client=client))
    with pytest.raises(ex.ExecutionError, match="still be live"):
        asyncio.run(ex.resolve(intent, ledger, confirm=True, now=2_000_000_050, client=client))
    late = 2_000_000_200
    client.open_orders = [open_order()]
    with pytest.raises(ex.ExecutionError, match="open order still matches"):
        asyncio.run(ex.resolve(intent, ledger, confirm=True, now=late, client=client))
    client.open_orders, client.pages = [], [[trade("a1")]]
    with pytest.raises(ex.ExecutionError, match="may be a fill"):
        asyncio.run(ex.resolve(intent, ledger, confirm=True, now=late, client=client))
    client.pages = [[]]
    result = asyncio.run(ex.resolve(intent, ledger, confirm=True, now=late, client=client))
    assert result["ok"] and result["phase"] == "ABORTED" and result["order_status"] == "NOT_PLACED"
    other, other_client = another_intent()
    assert submit(other, other_client, ledger)["phase"] == "ACCEPTED"  # the account is unblocked


def test_messages_name_the_real_state_of_a_refused_intent(setup):
    config, client, ledger = setup
    client.post_failure = RequestRejectedError("m", status=425)
    submit(config, client, ledger)
    status = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert "refused" in status["error"] and "recover" not in status["error"]
    with pytest.raises(ex.ExecutionError, match="refused"):
        asyncio.run(ex.cancel(config["intent_id"], ledger, confirm=True, client=client))


def test_ledger_path_must_be_a_regular_file(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir()
    mode = folder.stat().st_mode
    with pytest.raises(ValueError, match="regular file"):
        order_store.summary(folder)
    assert folder.stat().st_mode == mode  # a typo such as --ledger . must not change a folder's permissions
    target = tmp_path / "target"
    target.write_text("")
    link = tmp_path / "link.sqlite3"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="regular file"):
        order_store.summary(link)
    with order_store.connection(tmp_path / "new" / "orders.sqlite3"):  # a write path creates the ledger, private to the user
        pass
    assert order_store.summary(tmp_path / "new" / "orders.sqlite3")["intents"] == []
    assert (tmp_path / "new" / "orders.sqlite3").stat().st_mode & 0o777 == 0o600


def test_status_uses_each_maker_order_amount_and_deduplicates_updated_fills(setup):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.matched = "5"
    client.pages = [[trade("a1", role="MAKER", size="2")],
                    [trade("a2", state="MATCHED", size="3"), trade("a3", state="FAILED", size="1")]]
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["confirmed_filled_shares"] == "2" and result["pending_filled_shares"] == "3"
    assert result["failed_fill_shares"] == "1" and result["trades_complete"] is True
    assert result["fills"][0]["fee_estimate"] == "0.00000"  # maker contribution is 2, not trade's overall size 100
    client.pages[1][0].status = "CONFIRMED"
    client.pages[1][0].updated_at = datetime.now(timezone.utc)
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["confirmed_filled_shares"] == "5" and result["pending_filled_shares"] == "0"
    assert len(result["fills"]) == 3 and "estimates" in result["fee_notice"]


def test_partial_trade_pagination_and_order_404_are_not_proof_of_no_fills(setup):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.pages = [[trade("a1")], []]
    client.paging_failure = True
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["phase"] == "UNKNOWN" and result["trades_complete"] is False
    assert order_store.fills(ledger, config["intent_id"]) == []
    client.get_failure = LookupError("404 " + SECRET)
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["phase"] == "UNKNOWN" and SECRET not in json.dumps(result)


def test_cancel_remains_available_with_kill_switch_and_reports_confirmed_fills(setup, monkeypatch):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.pages = [[trade("a1", size="2")]]
    client.matched = "2"
    monkeypatch.setattr(ex.safety, "require_live", lambda *a: (_ for _ in ()).throw(AssertionError("KILL must not block cancel/status")))
    result = asyncio.run(ex.cancel(config["intent_id"], ledger, confirm=True, client=client))
    assert result["phase"] == "CANCELED" and result["confirmed_filled_shares"] == "2"
    assert result["unfilled_shares"] == "8" and result["remaining_open_shares"] == "0"


def test_preparing_intent_can_be_aborted_and_cannot_transition_to_post(setup):
    config, client, ledger = setup
    order_store.reserve(ledger, WALLET, ex._economic_plan(plan(config)))
    result = asyncio.run(ex.cancel(config["intent_id"], ledger, confirm=True, client=client))
    assert result["phase"] == "ABORTED"
    with pytest.raises(ValueError, match="changed state"):
        order_store.transition(ledger, config["intent_id"], "SUBMITTING", expected="PREPARING")
    assert "post" not in client.calls


def test_recovery_verifies_order_fields_before_linking_and_never_reposts(setup, monkeypatch):
    config, client, ledger = setup
    client.post_failure = TimeoutError(SECRET)
    submit(config, client, ledger)
    original = client.get_order

    async def wrong_order(**kwargs):
        order = await original(**kwargs)
        order.maker_address = "0x" + "f" * 40
        return order
    monkeypatch.setattr(client, "get_order", wrong_order)
    result = asyncio.run(ex.recover(config["intent_id"], ORDER_ID, ledger, client=client))
    assert result["ok"] is False and order_store.get(ledger, config["intent_id"])["order_id"] is None
    monkeypatch.setattr(client, "get_order", original)
    result = asyncio.run(ex.recover(config["intent_id"], ORDER_ID, ledger, client=client))
    assert result["ok"] is True and result["phase"] == "ACCEPTED" and client.calls.count("post") == 1


def test_undeployed_smart_wallet_is_rejected_before_sdk_create(setup, monkeypatch):
    config, client, ledger = setup
    monkeypatch.setenv("POLYMARKET_SIGNER_PRIVATE_KEY", "0x" + "01" * 32)

    class EmptyCode:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *args): return b'{"result":"0x"}'

    monkeypatch.setattr(ex.urllib.request, "urlopen", lambda *a, **k: EmptyCode())
    async def forbidden(**kwargs):
        raise AssertionError("SDK create must not deploy the wallet")
    monkeypatch.setattr(ex.AsyncSecureClient, "create", forbidden)
    async def authenticate():
        async with ex._secure():
            pass
    with pytest.raises(ex.ExecutionError, match="deployed-wallet verification"):
        asyncio.run(authenticate())


def test_eoa_does_not_require_contract_deployment_check(setup, monkeypatch):
    config, client, ledger = setup
    key = "0x" + "01" * 32
    wallet = Account.from_key(key).address
    monkeypatch.setenv("POLYMARKET_SIGNER_PRIVATE_KEY", key)
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", wallet)
    client.wallet = wallet

    async def create(**kwargs):
        assert kwargs["wallet"].lower() == wallet.lower() and kwargs["credentials"].key == SECRET
        return client
    monkeypatch.setattr(ex.AsyncSecureClient, "create", create)
    async def authenticate():
        async with ex._secure() as authenticated:
            assert authenticated is client
    asyncio.run(authenticate())
    assert "close" in client.calls


def test_sell_reads_inventory_allowance_for_selected_protocol(setup):
    config, client, ledger = setup
    config["side"] = "SELL"
    config["token_id"] = str(int("01" + "00" * 31, 16))
    config["version"] = "v2"
    result = submit(config, client, ledger)
    assert result["phase"] == "ACCEPTED"
    balances = [call[1] for call in client.calls if isinstance(call, tuple) and call[0] == "balance"]
    assert all(call["asset_type"] == "CONDITIONAL-V2" and call["asset_id"] == config["token_id"] for call in balances)


@pytest.mark.parametrize("confirm,live", [("wrong", True), (None, False)])
def test_confirmation_and_live_guard_run_before_authentication(setup, monkeypatch, confirm, live):
    config, client, ledger = setup

    @asynccontextmanager
    async def forbidden(*args):
        raise AssertionError("authentication must not begin")
        yield
    monkeypatch.setattr(ex, "_secure", forbidden)
    with pytest.raises((ex.ExecutionError, ex.safety.NotAllowed)):
        asyncio.run(ex.submit(config, ledger, confirm=confirm or plan(config)["plan_id"], live=live, client=client))
    assert "sign" not in client.calls and "post" not in client.calls and not ledger.exists()


def test_unrecognized_submission_response_blocks_new_intents(setup, monkeypatch):
    config, client, ledger = setup

    async def malformed(signed):
        return NS(ok="true", order_id=ORDER_ID, status="LIVE", secret=SECRET)
    monkeypatch.setattr(client, "post_order", malformed)
    result = submit(config, client, ledger)
    assert result["phase"] == "UNKNOWN" and SECRET not in json.dumps(result)
    with pytest.raises(ValueError, match="unresolved intent"):
        submit({"intent_id": str(uuid4())}, client, ledger)


@pytest.mark.parametrize("matched", ["NaN", "-1", "11"])
def test_invalid_matched_quantity_fails_closed_before_history_write(setup, matched):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.matched = matched
    client.pages = [[trade("a1")]]
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["phase"] == "UNKNOWN" and order_store.fills(ledger, config["intent_id"]) == []


def test_prebroadcast_trade_is_pending_and_open_quantity_is_reported(setup):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.matched = "2"
    client.pages = [[trade("a1", state="MATCHED_NOT_BROADCASTED")]]
    client.associate_trades = ("a1",)
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["pending_filled_shares"] == "2" and result["confirmed_filled_shares"] == "0"
    assert result["remaining_open_shares"] == "8" and result["unfilled_shares"] == "8"


def test_associated_trade_not_visible_yet_keeps_history_incomplete(setup):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.associate_trades = ("a1", "a2")
    client.pages = [[trade("a1")]]
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["trades_complete"] is False and result["phase"] == "UNKNOWN"
    assert order_store.fills(ledger, config["intent_id"]) == []
    client.pages[0].append(trade("a2"))
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["trades_complete"] is True and len(result["fills"]) == 2


def test_oversized_aggregate_rolls_back_all_new_fills(setup):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.pages = [[trade("a1", size="6"), trade("a2", size="5")]]
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["phase"] == "UNKNOWN" and order_store.fills(ledger, config["intent_id"]) == []


@pytest.mark.parametrize("change", ["role", "size", "price", "terminal_regression", "terminal_conflict"])
def test_conflicting_trade_update_cannot_rewrite_prior_fill(setup, change):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.pages = [[trade("a1")]]
    assert asyncio.run(ex.status(config["intent_id"], ledger, client=client))["ok"] is True
    prior = order_store.fills(ledger, config["intent_id"])
    updated = trade("a1", role="MAKER" if change == "role" else "TAKER")
    if change == "size": updated.size = Decimal("3")
    if change == "price": updated.price = Decimal("0.4")
    if change == "terminal_regression": updated.status = "MATCHED"
    if change == "terminal_conflict": updated.status = "FAILED"
    client.pages = [[trade("a2"), updated]]  # new row must roll back too
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["phase"] == "UNKNOWN" and order_store.fills(ledger, config["intent_id"]) == prior


def test_sdk_second_lookup_cannot_deploy_existing_wallet_client(monkeypatch):
    import polymarket.clients.async_secure as sdk
    client = ex._ExistingWalletClient.__new__(ex._ExistingWalletClient)
    client._ended = False
    client._ctx = NS(wallet_type="DEPOSIT_WALLET", relayer=object(), wallet=WALLET)

    async def absent(*args, **kwargs):
        return False
    monkeypatch.setattr(sdk, "fetch_deployed", absent)
    with pytest.raises(ex.ExecutionError, match="cannot deploy"):
        asyncio.run(client._ensure_wallet_ready())


@pytest.mark.parametrize("taker_only", [False, None])
def test_unsupported_or_unknown_maker_fee_schedule_rejected_before_signing(setup, monkeypatch, taker_only):
    config, client, ledger = setup

    async def preview(config, client=None):
        result = plan(config)
        if taker_only is None:
            del result["order"]["fee_schedule"]["taker_only"]
        else:
            result["order"]["fee_schedule"]["taker_only"] = taker_only
        return result
    monkeypatch.setattr(ex, "_preview", preview)
    with pytest.raises(ex.ExecutionError, match="taker-only"):
        submit(config, client, ledger)
    assert "sign" not in client.calls and "post" not in client.calls and not ledger.exists()


def test_late_live_poll_cannot_resurrect_concurrently_canceled_order(setup, monkeypatch):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.pages = [[trade("a1")]]
    client.matched = "2"
    original = client.list_account_trades
    first_poll = True

    def interleaved(**kwargs):
        paginator = original(**kwargs)

        async def fetch(cursor):
            nonlocal first_poll
            if first_poll:
                first_poll = False
                canceled = await ex.cancel(config["intent_id"], ledger, confirm=True, client=client)
                assert canceled["phase"] == "CANCELED"
            return await paginator.first_page()
        return AsyncPaginator(fetch)
    monkeypatch.setattr(client, "list_account_trades", interleaved)
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["phase"] == "CANCELED" and result["order_status"] == "CANCELED"
    assert result["remaining_open_shares"] == "0" and result["confirmed_filled_shares"] == "2"
    assert order_store.get(ledger, config["intent_id"])["order_status"] == "CANCELED"
    client.pages[0].append(trade("a2"))
    client.matched = "4"
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["confirmed_filled_shares"] == "4" and result["remaining_open_shares"] == "0"


@pytest.mark.parametrize("field,value", [
    ("asset_id", "different-outcome"), ("condition_id", "0x" + "e" * 64), ("side", "SELL"),
    ("original_size", Decimal("9")), ("price", Decimal("0.4")), ("order_type", "GTC"),
    ("expires_at", datetime.fromtimestamp(1_900_000_000, timezone.utc)),
    ("created_at", datetime.fromtimestamp(1, timezone.utc)),
])
def test_recovery_rejects_different_economics_or_submission_time(setup, field, value):
    config, client, ledger = setup
    client.post_failure = TimeoutError(SECRET)
    submit(config, client, ledger)
    client.remote_changes[field] = value
    result = asyncio.run(ex.recover(config["intent_id"], ORDER_ID, ledger, client=client))
    assert result["ok"] is False and order_store.get(ledger, config["intent_id"])["order_id"] is None
    assert client.calls.count("post") == 1


def test_trade_cursor_cycle_fails_instead_of_truncating_history(setup, monkeypatch):
    config, client, ledger = setup
    submit(config, client, ledger)

    def looping(**kwargs):
        async def fetch(cursor):
            return Page((trade("a1"),), has_more=True, next_cursor="same")
        return AsyncPaginator(fetch)
    monkeypatch.setattr(client, "list_account_trades", looping)
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["phase"] == "UNKNOWN" and result["trades_complete"] is False
    assert order_store.fills(ledger, config["intent_id"]) == []


def test_cancel_timeout_retains_uncertainty_without_claiming_canceled(setup):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.cancel_failure = TimeoutError(SECRET)
    result = asyncio.run(ex.cancel(config["intent_id"], ledger, confirm=True, client=client))
    assert result["phase"] == "UNKNOWN" and SECRET not in json.dumps(result)
    assert order_store.get(ledger, config["intent_id"])["order_status"] == "LIVE"


def test_positive_matched_quantity_without_visible_trades_is_incomplete(setup):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.matched = "2"
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["trades_complete"] is False and result["phase"] == "UNKNOWN"
    client.pages = [[trade("a1", state="FAILED")]]  # a known failed matching attempt also explains a server match
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["trades_complete"] is True and result["confirmed_filled_shares"] == "0"
    assert result["failed_fill_shares"] == "2" and result["unreconciled_matched_shares"] == "0"


@pytest.mark.parametrize("state", ["CANCELED", "EXPIRED"])
def test_cancel_of_already_terminal_server_order_only_reconciles(setup, state):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.order_status = state
    client.matched = "2"
    client.pages = [[trade("a1")]]
    client.cancel_failure = RuntimeError(SECRET)  # repeated cancel must never be needed
    for _ in range(2):
        result = asyncio.run(ex.cancel(config["intent_id"], ledger, confirm=True, client=client))
        assert result["phase"] == "CANCELED" and result["remaining_open_shares"] == "0"
        assert result["confirmed_filled_shares"] == "2"
    assert "cancel" not in client.calls


# ---- guards that a mutation test showed no earlier test could fail (RK-02), and the order id kept in the ledger (RK-14)
@pytest.mark.parametrize("tamper", [dict(maker_amount=lambda m: m * 2), dict(taker_amount=lambda t: t + 1), dict(token_id=lambda _: "999"),
                                    dict(side=lambda _: "SELL"), dict(maker=lambda _: "0x" + "2" * 40),
                                    dict(order_type=lambda _: "GTC"), dict(builder=lambda _: "0x" + "0" * 63 + "1"), dict(expiration=lambda e: e + 1), dict(post_only=lambda p: not p)])
def test_a_signed_order_that_differs_from_the_reviewed_plan_is_never_posted(setup, monkeypatch, tamper):
    config, client, ledger = setup
    real = client.create_limit_order

    async def tampered(**kwargs):
        signed = await real(**kwargs)
        for field, change in tamper.items():
            setattr(signed, field, change(getattr(signed, field)))
        return signed
    monkeypatch.setattr(client, "create_limit_order", tampered)
    with pytest.raises(ex.ExecutionError, match="differs from the reviewed"):
        submit(config, client, ledger)
    assert "post" not in client.calls and order_store.get(ledger, config["intent_id"])["phase"] == "ABORTED"


def test_the_balance_is_checked_again_after_signing(setup, monkeypatch):
    config, client, ledger = setup
    real = client.get_balance_allowance
    calls = []

    async def shrinking(**kwargs):
        calls.append(1)
        result = await real(**kwargs)
        return BalanceAllowance(balance=20_000_000 if len(calls) == 1 else 1, allowances=result.allowances)
    monkeypatch.setattr(client, "get_balance_allowance", shrinking)
    with pytest.raises(ex.ExecutionError):
        submit(config, client, ledger)
    assert "post" not in client.calls and len(calls) == 2


def test_recover_refuses_when_two_open_orders_match_and_never_guesses(setup):
    config, client, ledger = setup
    client.post_response = sdk_response("unmatched")
    submit(config, client, ledger)
    client.open_orders = [open_order(), open_order(id="0x" + "e" * 64)]  # identical economics, two ids
    result = asyncio.run(ex.recover(config["intent_id"], None, ledger, client=client))
    assert result["ok"] is False and order_store.get(ledger, config["intent_id"])["order_id"] is None


def test_a_failed_accepted_write_keeps_the_order_id_and_recover_cannot_swap_it(setup, monkeypatch):
    config, client, ledger = setup
    real = order_store.transition

    def flaky(path, intent_id, phase, **kwargs):
        if phase == "ACCEPTED":
            raise RuntimeError("database is locked")
        return real(path, intent_id, phase, **kwargs)
    monkeypatch.setattr(order_store, "transition", flaky)
    result = submit(config, client, ledger)
    assert result["phase"] == "UNKNOWN" and result["order_id"] == ORDER_ID and f"--order-id {ORDER_ID}" in result["error"]
    assert order_store.get(ledger, config["intent_id"])["order_id"] == ORDER_ID  # kept with the UNKNOWN row (RK-14)
    with pytest.raises(ex.ExecutionError, match="same unresolved intent"):
        asyncio.run(ex.recover(config["intent_id"], "0x" + "9" * 64, ledger, client=client))


def test_resolve_refuses_an_unknown_intent_whose_order_id_is_known(setup, monkeypatch):
    config, client, ledger = setup
    real = order_store.transition

    def flaky(path, intent_id, phase, **kwargs):
        if phase == "ACCEPTED":
            raise RuntimeError("database is locked")
        return real(path, intent_id, phase, **kwargs)
    monkeypatch.setattr(order_store, "transition", flaky)
    assert submit(config, client, ledger)["phase"] == "UNKNOWN"  # the exchange holds the order, the ledger says UNKNOWN with its ID
    with pytest.raises(ex.ExecutionError, match="without a server order ID"):
        asyncio.run(ex.resolve(config["intent_id"], ledger, confirm=True, now=2_000_000_500, client=client))
    assert order_store.get(ledger, config["intent_id"])["phase"] == "UNKNOWN"  # still blocking the account


def test_resolve_refuses_an_intent_that_is_already_closed(setup):
    config, client, ledger = setup
    client.post_response = sdk_response("unmatched")
    submit(config, client, ledger)
    order_store.transition(ledger, config["intent_id"], "ABORTED", expected="UNKNOWN")
    with pytest.raises(ex.ExecutionError, match="without a server order ID"):
        asyncio.run(ex.resolve(config["intent_id"], ledger, confirm=True, now=2_000_000_500, client=client))


def test_resolve_refuses_an_intent_that_belongs_to_another_account(setup, monkeypatch):
    config, client, ledger = setup
    client.post_response = sdk_response("unmatched")
    submit(config, client, ledger)
    other = "0x" + "1" * 40
    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", other)
    with pytest.raises(ex.ExecutionError, match="does not own"):
        asyncio.run(ex.resolve(config["intent_id"], ledger, confirm=True, now=2_000_000_500, client=NS(wallet=other)))
    assert order_store.get(ledger, config["intent_id"])["phase"] == "UNKNOWN"


def test_a_ledger_path_that_is_an_existing_non_ledger_file_is_refused_without_changing_it(tmp_path):
    import os
    stray = tmp_path / "notes.txt"
    stray.write_text("my notes")
    os.chmod(stray, 0o644)
    with pytest.raises(ValueError, match="not an order ledger"):
        order_store.get(stray, str(uuid4()))
    assert stray.read_text() == "my notes" and (os.stat(stray).st_mode & 0o777) == 0o644


def test_a_ledger_that_is_down_after_the_exchange_accepted_the_order_still_reports_the_order_id(setup, monkeypatch):
    import sqlite3
    config, client, ledger = setup
    real_transition, real_get = order_store.transition, order_store.get

    def transition(path, intent_id, phase, **kwargs):
        if "post" in client.calls:
            raise sqlite3.OperationalError("disk I/O error")
        return real_transition(path, intent_id, phase, **kwargs)

    def get(path, intent_id):
        if "post" in client.calls:
            raise sqlite3.OperationalError("disk I/O error")
        return real_get(path, intent_id)
    monkeypatch.setattr(order_store, "transition", transition)
    monkeypatch.setattr(order_store, "get", get)
    with pytest.raises(ex.ExecutionError, match=ORDER_ID):  # not a bare database error that hides an order that exists (RK-04)
        submit(config, client, ledger)
    assert client.calls.count("post") == 1


def test_a_failing_ledger_is_reported_as_it_is_when_no_order_was_accepted(setup, monkeypatch):
    import sqlite3
    config, client, ledger = setup
    real_get = order_store.get

    async def failing_sign(**kwargs):
        client.calls.append("sign")
        raise RuntimeError("signer failed")

    def get(path, intent_id):
        if "sign" in client.calls:
            raise sqlite3.OperationalError("disk I/O error")
        return real_get(path, intent_id)
    monkeypatch.setattr(client, "create_limit_order", failing_sign)
    monkeypatch.setattr(order_store, "get", get)
    with pytest.raises(sqlite3.OperationalError):  # nothing was posted, so the ledger error is the whole story and is not swallowed
        submit(config, client, ledger)
    assert "post" not in client.calls


def test_a_repeating_page_cursor_stops_recover_and_resolve_instead_of_looping_forever(setup):
    config, client, ledger = setup
    client.post_response = sdk_response("unmatched")
    submit(config, client, ledger)

    def looping(**kwargs):
        async def fetch(cursor):
            return Page((), has_more=True, next_cursor="same")
        return AsyncPaginator(fetch)
    real_orders, real_trades = client.list_open_orders, client.list_account_trades
    client.list_open_orders = looping
    result = asyncio.run(asyncio.wait_for(ex.recover(config["intent_id"], None, ledger, client=client), 10))
    assert result["ok"] is False and "repeated a page cursor" in result["error"] and result["phase"] == "UNKNOWN"
    client.list_open_orders, client.list_account_trades = real_orders, looping
    with pytest.raises(ex.ExecutionError, match="repeated a page cursor"):
        asyncio.run(asyncio.wait_for(ex.resolve(config["intent_id"], ledger, confirm=True, now=2_000_000_500, client=client), 10))
    assert order_store.get(ledger, config["intent_id"])["phase"] == "UNKNOWN"  # nothing was closed on an incomplete list
    client.list_account_trades = real_trades
    asyncio.run(ex.resolve(config["intent_id"], ledger, confirm=True, now=2_000_000_500, client=client))
    assert order_store.get(ledger, config["intent_id"])["phase"] == "ABORTED"


def test_reading_a_ledger_that_does_not_exist_creates_nothing(tmp_path):
    missing = tmp_path / "typo" / "orders.sqlite3"
    assert order_store.summary(missing) == {"intents": [], "fills": []}
    assert order_store.fills(missing, "x") == []
    with pytest.raises(ValueError, match="No order ledger exists"):
        order_store.get(missing, str(uuid4()))
    assert not (tmp_path / "typo").exists()  # a mistyped --ledger leaves no stray folder or empty database (RK-19)


# ---- guards that RK's mutation run found no test could fail (second revision)
def trades_of(client):
    return [call[1] for call in client.calls if isinstance(call, tuple) and call[0] == "trades"]


@pytest.mark.parametrize("change", [lambda p: p["order"].update(size="0"), lambda p: p["order"].update(price="1.5"), lambda p: p["order"].update(price="0"),
                                    lambda p: p["order"].update(post_only="no"), lambda p: p["order"].update(neg_risk=True),
                                    lambda p: p["order"].update(version="v3"), lambda p: p["order"].update(side="HOLD")])
def test_an_impossible_order_in_the_plan_is_refused_before_anything_is_reserved_or_signed(setup, monkeypatch, change):
    config, client, ledger = setup

    async def preview(config, client=None):
        result = plan(config)
        change(result)
        return result
    monkeypatch.setattr(ex, "_preview", preview)
    with pytest.raises(ex.ExecutionError):
        asyncio.run(ex.submit(config, ledger, confirm=plan(config)["plan_id"], live=True, client=client))
    assert "sign" not in client.calls and "post" not in client.calls and not ledger.exists()


def test_a_wrong_plan_id_or_an_ineligible_preview_never_reaches_the_exchange(setup, monkeypatch):
    config, client, ledger = setup
    with pytest.raises(ex.ExecutionError, match="exact plan ID"):
        asyncio.run(ex.submit(config, ledger, confirm="0" * 16, live=True, client=client))

    async def ineligible(config, client=None):
        return {**plan(config), "eligible": False}
    monkeypatch.setattr(ex, "_preview", ineligible)
    with pytest.raises(ex.ExecutionError, match="exact plan ID"):
        asyncio.run(ex.submit(config, ledger, confirm=plan(config)["plan_id"], live=True, client=client))
    assert "sign" not in client.calls and "post" not in client.calls


def test_a_prepared_intent_that_never_reached_the_exchange_still_blocks_a_second_one(setup):
    config, client, ledger = setup
    account = ex._wallet()
    order_store.reserve(ledger, account, ex._economic_plan(plan(config)))  # PREPARING
    other, _ = another_intent()
    with pytest.raises(ValueError, match="unresolved intent"):
        order_store.reserve(ledger, account, ex._economic_plan(plan(other)))
    asyncio.run(ex.cancel(config["intent_id"], ledger, confirm=True, client=client))  # aborting it frees the account
    order_store.reserve(ledger, account, ex._economic_plan(plan(other)))


def test_cancel_needs_explicit_confirmation_and_sends_nothing_without_it(setup):
    config, client, ledger = setup
    submit(config, client, ledger)
    for confirm in (False, None, 1, "yes"):
        with pytest.raises(ex.ExecutionError, match="confirmation"):
            asyncio.run(ex.cancel(config["intent_id"], ledger, confirm=confirm, client=client))
    assert "cancel" not in client.calls


def test_status_does_not_accept_a_buy_fill_above_the_limit_or_an_unlisted_order_status(setup):
    config, client, ledger = setup
    submit(config, client, ledger)
    dear = NS(**{**vars(trade("a1")), "price": Decimal("0.51")})  # the BUY limit is 0.50
    client.pages = [[dear]]
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["ok"] is False and result["phase"] == "UNKNOWN" and order_store.fills(ledger, config["intent_id"]) == []
    client.pages = [[]]
    client.order_status = "WEIRD"
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["ok"] is False and result["phase"] == "UNKNOWN"
    client.order_status = "LIVE"
    assert asyncio.run(ex.status(config["intent_id"], ledger, client=client))["ok"] is True  # and a good poll heals it


def test_resolve_asks_only_for_trades_since_the_intent_was_created_and_ignores_opposite_side_trades(setup):
    config, client, ledger = setup
    client.post_response = sdk_response("unmatched")
    submit(config, client, ledger)
    created = order_store.get(ledger, config["intent_id"])["created_at"]
    opposite = NS(**{**vars(trade("s1")), "side": "SELL"})  # same token and account, other side: not a fill of this BUY
    client.pages = [[opposite]]
    result = asyncio.run(ex.resolve(config["intent_id"], ledger, confirm=True, now=2_000_000_500, client=client))
    assert result["ok"] is True
    assert trades_of(client)[-1]["after"] == str(int(created - 60))


def test_recover_ignores_orders_created_outside_the_intents_own_window(setup):
    from datetime import timedelta
    config, client, ledger = setup
    client.post_response = sdk_response("unmatched")
    submit(config, client, ledger)
    now = datetime.now(timezone.utc)
    for created in (now - timedelta(hours=2), now + timedelta(minutes=10)):
        client.open_orders = [open_order(created_at=created)]
        result = asyncio.run(ex.recover(config["intent_id"], None, ledger, client=client))
        assert result["ok"] is False and "No single open order matches" in result["error"]
    client.open_orders = [open_order(created_at=now)]
    assert asyncio.run(ex.recover(config["intent_id"], None, ledger, client=client))["ok"] is True


def test_resolve_cannot_overwrite_an_intent_that_another_command_just_recovered(setup):
    config, client, ledger = setup
    client.post_response = sdk_response("unmatched")
    submit(config, client, ledger)
    real = client.list_account_trades

    def racing(**kwargs):  # between resolve's read of the row and its write, another command attaches the order
        order_store.transition(ledger, config["intent_id"], "ACCEPTED", order_id=ORDER_ID, order_status="LIVE")
        return real(**kwargs)
    client.list_account_trades = racing
    with pytest.raises(ValueError, match="changed state"):
        asyncio.run(ex.resolve(config["intent_id"], ledger, confirm=True, now=2_000_000_500, client=client))
    assert order_store.get(ledger, config["intent_id"])["phase"] == "ACCEPTED"


def test_the_deployed_wallet_check_names_the_tool_and_refuses_a_wallet_without_code(setup, monkeypatch):
    from polymarket_strategies import safety
    seen, code = [], {"value": "0x6080"}
    monkeypatch.setattr(ex.urllib.request, "urlopen", lambda request, timeout=None: _json_reply(seen, request, code["value"]))
    asyncio.run(ex._deployed_wallet("0x" + "1" * 40, "0x" + "2" * 40))
    assert seen[0].get_header("User-agent") == safety.USER_AGENT and b"eth_getCode" in seen[0].data
    code["value"] = "0x"
    with pytest.raises(ex.ExecutionError, match="deployed"):
        asyncio.run(ex._deployed_wallet("0x" + "1" * 40, "0x" + "2" * 40))
    asyncio.run(ex._deployed_wallet("0x" + "3" * 40, "0x" + "3" * 40))  # an ordinary account has no contract to look for: no request
    assert len(seen) == 2


def _json_reply(seen, request, code):
    seen.append(request)

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *args):
            return json.dumps({"jsonrpc": "2.0", "id": 1, "result": code}).encode()
    return Reply()


def test_status_does_not_accept_a_fill_larger_than_the_order(setup):
    config, client, ledger = setup
    submit(config, client, ledger)
    client.pages = [[trade("a1", size="11")]]  # the order is for 10 shares
    result = asyncio.run(ex.status(config["intent_id"], ledger, client=client))
    assert result["ok"] is False and result["phase"] == "UNKNOWN" and order_store.fills(ledger, config["intent_id"]) == []


def test_an_allowance_smaller_than_the_cash_bound_does_not_authorize_the_order(setup, monkeypatch):
    config, client, ledger = setup
    real = client.get_balance_allowance

    async def small(**kwargs):
        result = await real(**kwargs)
        return BalanceAllowance(balance=result.balance, allowances={address: 1_000_000 for address in result.allowances})
    monkeypatch.setattr(client, "get_balance_allowance", small)
    with pytest.raises(ex.ExecutionError, match="Insufficient"):
        submit(config, client, ledger)
    assert "sign" not in client.calls and "post" not in client.calls


def test_a_client_for_another_wallet_than_the_configured_account_is_refused(setup, monkeypatch):
    config, client, ledger = setup
    with pytest.raises(ex.ExecutionError, match="does not match"):
        ex._wallet(NS(wallet="0x" + "7" * 40))  # an injected client
    closed = []

    class Owned:
        wallet = "0x" + "9" * 40

        async def close(self):
            closed.append(True)

    async def create(**kwargs):
        return Owned()

    async def deployed(wallet, signer):
        return None
    monkeypatch.setattr(ex._ExistingWalletClient, "create", create)
    monkeypatch.setattr(ex, "_deployed_wallet", deployed)
    monkeypatch.setattr(ex.Account, "from_key", lambda key: NS(address="0x" + "8" * 40))

    async def use():
        async with ex._secure() as authenticated:
            return authenticated
    with pytest.raises(ex.ExecutionError, match="does not match"):
        asyncio.run(use())
    assert closed  # and the connection is still closed
