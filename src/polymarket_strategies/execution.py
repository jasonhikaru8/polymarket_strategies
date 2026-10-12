"""Reader-controlled single limit orders. Accepted orders and confirmed fills are different states."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal, ROUND_CEILING
import json
import os
import re
import time
import urllib.request
from uuid import UUID

from eth_account import Account
from polymarket import ApiKeyCreds, AsyncSecureClient, PRODUCTION
from polymarket.errors import RateLimitError, RequestRejectedError
from polymarket._internal.actions.orders.context import resolve_order_exchange_address
from polymarket._internal.environment import get_environment_config
from polymarket._internal.protocol import is_v2_position_id

from . import order_store, safety

_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
_ORDER_ID = re.compile(r"0x[0-9a-fA-F]{64}\Z")
_BASE = Decimal(1_000_000)
_PENDING_TRADE_STATES = {"MATCHED_NOT_BROADCASTED", "MATCHED", "MINED", "RETRYING"}
_TRADE_STATES = _PENDING_TRADE_STATES | {"CONFIRMED", "FAILED"}


class ExecutionError(RuntimeError):
    """A deliberately sanitized operational error."""


class _ExistingWalletClient(AsyncSecureClient):
    async def _deploy_default_deposit_wallet(self):
        # SDK 0.11.0 create() may otherwise deploy a Deposit Wallet after its second existence check.
        raise ExecutionError("This reader command cannot deploy a wallet.")


def _number(value):
    try:
        result = Decimal(str(value))
    except Exception:
        raise ExecutionError("Invalid economic number.") from None
    if not result.is_finite():
        raise ExecutionError("Economic numbers must be finite.")
    return result


def _wallet(client=None):
    account = os.environ.get("POLYMARKET_WALLET_ADDRESS", "")
    if not _ADDRESS.fullmatch(account):
        raise ExecutionError("Set a valid existing POLYMARKET_WALLET_ADDRESS.")
    if client is not None and str(client.wallet).lower() != account.lower():
        raise ExecutionError("Authenticated wallet does not match the configured account.")
    return account.lower()


async def _deployed_wallet(wallet, signer):
    if wallet.lower() == signer.lower():
        return  # an EOA has no deployed contract

    def read_code():
        config = get_environment_config(PRODUCTION)
        request = urllib.request.Request(config.rpc_url, data=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "eth_getCode", "params": [wallet, "latest"]
        }).encode(), headers={"Content-Type": "application/json", "User-Agent": safety.USER_AGENT})
        with urllib.request.urlopen(request, timeout=10) as response:
            answer = json.load(response)
        code = answer.get("result")
        if answer.get("error") or not isinstance(code, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", code) or int(code, 16) == 0:
            raise ExecutionError("The existing smart wallet could not be verified as deployed.")

    await asyncio.to_thread(read_code)


@asynccontextmanager
async def _secure(client=None):
    wallet = _wallet(client)
    if client is not None:
        yield client
        return
    try:
        private_key = os.environ["POLYMARKET_SIGNER_PRIVATE_KEY"]
        credentials = ApiKeyCreds(key=os.environ["POLYMARKET_API_KEY"], secret=os.environ["POLYMARKET_API_SECRET"],
                                  passphrase=os.environ["POLYMARKET_API_PASSPHRASE"])
        if not all((private_key, credentials.key, credentials.secret, credentials.passphrase)):
            raise ValueError
        signer = Account.from_key(private_key).address
        await _deployed_wallet(wallet, signer)
        owned = await _ExistingWalletClient.create(private_key=private_key, wallet=wallet, credentials=credentials)
    except Exception:
        raise ExecutionError("Authentication or deployed-wallet verification failed; no order was submitted.") from None
    try:
        if str(owned.wallet).lower() != wallet:
            raise ExecutionError("Authenticated wallet does not match the configured account.")
        yield owned
    finally:
        await owned.close()


async def pusd_balance(client=None):
    """Read-only: the account's pUSD balance and what each exchange contract is allowed to spend."""
    async with _secure(client) as authenticated:
        found = await authenticated.get_balance_allowance(asset_type="COLLATERAL")
    return {"pusd_balance": str(Decimal(found.balance) / _BASE),
            "pusd_allowance_by_exchange": {str(address): str(Decimal(value) / _BASE) for address, value in found.allowances.items()}}


async def _preview(config, client=None):
    from .trade_plan import preview
    return await preview(config, client=client)


def _economic_plan(plan):
    """Whitelist economic fields: never persist a signed order, config note, or SDK response."""
    order = plan["order"]
    intent_id = str(UUID(plan["intent_id"]))
    if order["side"] not in {"BUY", "SELL"} or order["version"] not in {"v1", "v2"} or order["neg_risk"] is not False:
        raise ExecutionError("Only standard binary limit orders are supported.")
    token_id = str(order["token_id"])
    if not re.fullmatch(r"(?:[0-9]+|0x[0-9a-fA-F]+)", token_id) or not _ORDER_ID.fullmatch(str(order["condition_id"])):
        raise ExecutionError("Invalid market identifiers.")
    size, price = _number(order["size"]), _number(order["price"])
    if size <= 0 or not 0 < price < 1 or type(order["post_only"]) is not bool:
        raise ExecutionError("Invalid limit order.")
    schedule = order["fee_schedule"]
    if schedule.get("taker_only") is not True:
        raise ExecutionError("Only explicit taker-only fee schedules are supported.")
    out = {key: str(plan[key]) for key in ("plan_id", "config_hash", "contract_fingerprint")}
    if any(not re.fullmatch(r"[0-9a-f]{16,64}", value) for value in out.values()):
        raise ExecutionError("Invalid plan fingerprint.")
    out.update(intent_id=intent_id, cash_bound=str(_number(plan["cash_bound"])), fee_bound=str(_number(plan["fee_bound"])),
               order={"token_id": token_id, "condition_id": str(order["condition_id"]), "side": order["side"],
                      "size": str(size), "price": str(price), "expiration": int(order["expiration"]),
                      "post_only": order["post_only"], "neg_risk": False, "version": order["version"],
                      "fee_schedule": {"rate": str(_number(schedule["rate"])),
                                       "exponent": str(_number(schedule["exponent"])), "taker_only": True}},
               quote={key: str(_number(plan["quote"][key])) for key in ("tick_size", "min_order_size")})
    return out


async def _balance(client, plan):
    order = plan["order"]
    buying = order["side"] == "BUY"
    asset_type = "COLLATERAL" if buying else ("CONDITIONAL-V2" if is_v2_position_id(order["token_id"]) else "CONDITIONAL")
    kwargs = {"asset_type": asset_type}
    if not buying:
        kwargs["asset_id"] = order["token_id"]
    balance = await client.get_balance_allowance(**kwargs)
    exchange = str(resolve_order_exchange_address(get_environment_config(PRODUCTION), asset_id=order["token_id"], neg_risk=False)).lower()
    required = int((_number(plan["cash_bound"] if buying else order["size"]) * _BASE).to_integral_value(rounding=ROUND_CEILING))
    allowance = next((int(value) for address, value in balance.allowances.items() if address.lower() == exchange), None)
    if int(balance.balance) < required or allowance is None or allowance < required:
        raise ExecutionError("Insufficient balance or allowance for the selected exchange; this command never approves spending.")
    return str(Decimal(balance.balance) / _BASE)


def _signed_matches(signed, plan, account):
    order = plan["order"]
    quantity = int(_number(order["size"]) * _BASE)
    notional = int(_number(order["size"]) * _number(order["price"]) * _BASE)
    maker, taker = (notional, quantity) if order["side"] == "BUY" else (quantity, notional)
    if (str(signed.maker).lower() != account or str(signed.token_id) != order["token_id"]
            or signed.side != order["side"] or signed.maker_amount != maker or signed.taker_amount != taker
            or signed.expiration != order["expiration"] or signed.post_only != order["post_only"]
            or signed.order_type != "GTD" or int(str(signed.builder), 16) != 0):  # a time-limited order with no builder attribution, as reviewed
        raise ExecutionError("Signed order differs from the reviewed limit order.")


# Responses that prove the exchange did not place the order. "unmatched" means placement still succeeded (the SDK then
# hides the order ID) and "unknown" is an unclassified failure, so both stay uncertain and keep the account blocked.
_REFUSED_CODES = {"market_not_ready", "not_enough_balance", "invalid_nonce", "invalid_expiration", "post_only_would_cross",
                  "post_only_mode", "fok_not_filled", "fak_not_filled"}


def _refusal(error):
    """Why an exception proves the exchange refused the order (an HTTP 4xx or 503, or a rate limit); None when the outcome is uncertain."""
    if isinstance(error, RateLimitError):
        return "rate limit"
    if isinstance(error, RequestRejectedError) and (400 <= error.status < 500 or error.status == 503):
        return f"HTTP {error.status}"
    return None


def _unknown_submission(intent_id, response=None):
    order_id = str(getattr(response, "order_id", "") or "")
    if _ORDER_ID.fullmatch(order_id):
        return {"ok": False, "intent_id": intent_id, "phase": "UNKNOWN", "order_id": order_id,
                "error": f"The exchange accepted order {order_id}, but this intent could not be marked accepted. Run `trade recover {intent_id} --order-id {order_id}`."}
    hidden = "The exchange reported that the order was placed but returned no order ID. " if getattr(response, "code", None) == "unmatched" else ""
    return {"ok": False, "intent_id": intent_id, "phase": "UNKNOWN",
            "error": f"{hidden}Submission outcome is unknown. Do not retry. Run `trade recover {intent_id}` to look for the order in your account."}


async def submit(config, ledger_path, *, confirm, live, client=None):
    plan = await _preview(config)
    if not plan["eligible"] or confirm != plan["plan_id"]:
        raise ExecutionError("An eligible fresh preview and its exact plan ID are required.")
    safe_plan = _economic_plan(plan)
    safety.require_live(live)
    account = _wallet(client)
    order_store.reserve(ledger_path, account, safe_plan)
    intent_id = safe_plan["intent_id"]
    posted_id = None
    try:
        async with _secure(client) as authenticated:
            await _balance(authenticated, safe_plan)
            order = safe_plan["order"]
            signed = await authenticated.create_limit_order(token_id=order["token_id"], side=order["side"],
                price=order["price"], size=order["size"], expiration=order["expiration"], post_only=order["post_only"])
            _signed_matches(signed, safe_plan, account)
            refreshed = await _preview(config, client=authenticated)
            if not refreshed["eligible"] or _economic_plan(refreshed) != safe_plan:
                raise ExecutionError("Market rules, fees, tick size or reviewed order bounds changed; preview again.")
            await _balance(authenticated, safe_plan)
            safety.require_live(live)
            order_store.transition(ledger_path, intent_id, "SUBMITTING", expected="PREPARING")
            response = None
            try:
                response = await authenticated.post_order(signed)
                if response.ok is True and _ORDER_ID.fullmatch(str(response.order_id)):
                    posted_id = str(response.order_id)
                    state = str(response.status).upper()
                    if state not in {"LIVE", "MATCHED", "DELAYED"}:
                        raise ExecutionError("Unknown submission status.")
                    order_store.transition(ledger_path, intent_id, "ACCEPTED", expected="SUBMITTING", order_id=posted_id, order_status=state)
                elif response.ok is False and str(getattr(response, "code", "")) in _REFUSED_CODES:
                    order_store.transition(ledger_path, intent_id, "REJECTED", expected="SUBMITTING")
                    return {"ok": False, "intent_id": intent_id, "phase": "REJECTED",
                            "error": f"Polymarket refused the order ({response.code}); nothing was placed."}
                else:
                    raise ExecutionError("Uncertain submission response.")
            except BaseException as error:
                refused = _refusal(error) if isinstance(error, Exception) else None
                try:
                    if refused:
                        order_store.transition(ledger_path, intent_id, "REJECTED", expected="SUBMITTING")
                    else:
                        order_store.transition(ledger_path, intent_id, "UNKNOWN", **({"order_id": posted_id} if posted_id else {}))
                except ValueError:
                    refused = None
                    order_store.transition(ledger_path, intent_id, "UNKNOWN", **({"order_id": posted_id} if posted_id else {}))
                if not isinstance(error, Exception):
                    raise
                if refused:
                    return {"ok": False, "intent_id": intent_id, "phase": "REJECTED",
                            "error": f"Polymarket refused the order ({refused}); nothing was placed."}
                return _unknown_submission(intent_id, response)
    except BaseException as error:
        try:
            if order_store.get(ledger_path, intent_id)["phase"] == "PREPARING":
                order_store.transition(ledger_path, intent_id, "ABORTED", expected="PREPARING")
        except Exception:
            if not posted_id:  # without an accepted order a failing ledger is the whole story; with one, the order ID must not be hidden by it
                raise
        if not isinstance(error, Exception):
            raise
        if isinstance(error, (ExecutionError, safety.NotAllowed)):
            raise
        if posted_id:
            raise ExecutionError(f"The exchange accepted order {posted_id}, but the local ledger could not record it. Run `trade recover {intent_id} --order-id {posted_id}`.") from None
        raise ExecutionError("Order preparation failed; inspect the local intent. No automatic retry was attempted.") from None
    row = order_store.get(ledger_path, intent_id)
    return {"ok": row["phase"] == "ACCEPTED", "intent_id": intent_id, "phase": row["phase"], "order_id": row["order_id"], "order_status": row["order_status"], "filled_shares": "not yet reconciled",
            "fee_notice": "The cash/fee reserve is modeled; match-time fees may differ. A BUY fee is paid in pUSD on top of price x shares and every matched share is delivered. Signed size and later matched quantities are share counts; current holdings are read separately."}


def _timestamp(value):
    return value.timestamp() if hasattr(value, "timestamp") else float(value)


def _validate_order(order, row):
    expected = row["plan"]["order"]
    created = _timestamp(order.created_at)
    if (str(order.id) != row["order_id"] or str(order.maker_address).lower() != row["account"]
            or str(order.asset_id) != expected["token_id"] or str(order.condition_id) != expected["condition_id"]
            or order.side != expected["side"] or _number(order.original_size) != _number(expected["size"])
            or _number(order.price) != _number(expected["price"])
            or str(order.order_type).upper() != "GTD" or order.expires_at is None
            or _timestamp(order.expires_at) != expected["expiration"]
            or not row["submitted_at"] or not row["created_at"] - 60 <= created <= row["submitted_at"] + 300):
        raise ExecutionError("Server order does not match this account and stored intent.")


def _fill(trade, row):
    order = row["plan"]["order"]
    if str(trade.taker_order_id) == row["order_id"]:
        source, role, quantity = trade, "TAKER", trade.size
    else:
        makers = [maker for maker in trade.maker_orders if str(maker.order_id) == row["order_id"]]
        if not makers:
            return None
        if len(makers) != 1:
            raise ExecutionError("Ambiguous maker fill.")
        source, role, quantity = makers[0], "MAKER", makers[0].matched_amount
    size, price = _number(quantity), _number(source.price)
    state = str(trade.status).upper()
    if (str(source.asset_id) != order["token_id"] or source.side != order["side"]
            or str(source.maker_address).lower() != row["account"] or str(trade.condition_id) != order["condition_id"]
            or size <= 0 or size > _number(order["size"]) or not 0 < price < 1 or state not in _TRADE_STATES
            or (order["side"] == "BUY" and price > _number(order["price"]))
            or (order["side"] == "SELL" and price < _number(order["price"]))):
        raise ExecutionError("Trade does not match the stored economic intent.")
    schedule = order["fee_schedule"]
    fee = Decimal(0) if role == "MAKER" else size * _number(schedule["rate"]) * (price * (1 - price)) ** _number(schedule["exponent"])
    trade_id = str(trade.id)
    if not re.fullmatch(r"[0-9a-fA-F-]{1,80}", trade_id):
        raise ExecutionError("Invalid trade identifier.")
    return {"trade_id": trade_id, "role": role, "size": str(size), "price": str(price), "status": state,
            "fee_estimate": str(fee.quantize(Decimal("0.00001"))), "updated_at": _timestamp(trade.updated_at)}


async def _items(pages, what):
    """Every item of a paginated answer. A page that promises more without a new cursor would repeat forever, so that is an error."""
    cursors = set()
    async for page in pages:
        if page.has_more:
            if page.next_cursor is None or page.next_cursor in cursors:
                raise ExecutionError(f"The {what} could not be read completely (the exchange repeated a page cursor).")
            cursors.add(page.next_cursor)
        for item in page.items:
            yield item


async def _reconcile(client, row, ledger_path):
    order = await client.get_order(order_id=row["order_id"])
    _validate_order(order, row)
    matched = _number(order.size_matched)
    if not 0 <= matched <= _number(row["plan"]["order"]["size"]):
        raise ExecutionError("Invalid reported matched quantity.")
    fills = []
    pages = client.list_account_trades(market=row["plan"]["order"]["condition_id"], after=str(int(row["created_at"] - 60)))
    async for trade in _items(pages, "trade history"):
        fill = _fill(trade, row)
        if fill is not None:
            fills.append(fill)
    order_store.save_fills(ledger_path, row["intent_id"], fills,
                          required_trade_ids=order.associate_trades, reported_matched=matched)
    saved = order_store.fills(ledger_path, row["intent_id"])
    confirmed = sum((_number(fill["size"]) for fill in saved if fill["status"] == "CONFIRMED"), Decimal(0))
    pending = sum((_number(fill["size"]) for fill in saved if fill["status"] in _PENDING_TRADE_STATES), Decimal(0))
    failed = sum((_number(fill["size"]) for fill in saved if fill["status"] == "FAILED"), Decimal(0))
    asset_type = "CONDITIONAL-V2" if is_v2_position_id(row["plan"]["order"]["token_id"]) else "CONDITIONAL"
    holdings = await client.get_balance_allowance(asset_type=asset_type, asset_id=row["plan"]["order"]["token_id"])
    state = str(order.status).upper()
    if state not in {"LIVE", "MATCHED", "DELAYED", "UNMATCHED", "CANCELED", "CANCELLED", "EXPIRED", "INVALID"}:
        raise ExecutionError("Unknown current order status.")
    phase = "CANCELED" if state in {"CANCELED", "CANCELLED", "EXPIRED"} else "ACCEPTED"
    effective = order_store.transition(ledger_path, row["intent_id"], phase, order_status=state)
    phase, state = effective["phase"], effective["order_status"]
    unfilled = _number(row["plan"]["order"]["size"]) - matched
    remaining = Decimal(0) if state in {"CANCELED", "CANCELLED", "EXPIRED", "INVALID"} else unfilled
    return {"ok": True, "intent_id": row["intent_id"], "order_id": row["order_id"], "phase": phase,
            "order_status": state, "matched_shares": str(order.size_matched), "confirmed_filled_shares": str(confirmed),
            "pending_filled_shares": str(pending), "failed_fill_shares": str(failed), "trades_complete": True,
            "unfilled_shares": str(unfilled), "remaining_open_shares": str(remaining),
            "unreconciled_matched_shares": str(max(Decimal(0), matched - confirmed - pending - failed)),
            "current_outcome_holdings": str(Decimal(holdings.balance) / _BASE), "fills": saved,
            "fee_notice": "Fill fees are estimates, not receipts. A BUY fee is paid in pUSD on top of price x shares and every matched share is delivered; a SELL fee comes out of the proceeds. Current holdings are a separate account balance including prior positions. New matches may appear in history later."}


async def status(intent_id, ledger_path, *, client=None):
    intent_id = str(UUID(intent_id))
    row = order_store.get(ledger_path, intent_id)
    if not row["order_id"]:
        return {"ok": False, "intent_id": intent_id, "phase": row["phase"], "safe_to_abort": row["phase"] == "PREPARING",
                "error": _no_order_message(row["phase"], intent_id)}
    if _wallet(client) != row["account"]:
        raise ExecutionError("Configured account does not own this intent.")
    try:
        async with _secure(client) as authenticated:
            return await _reconcile(authenticated, row, ledger_path)
    except Exception:
        order_store.transition(ledger_path, intent_id, "UNKNOWN")
        return {"ok": False, "intent_id": intent_id, "phase": "UNKNOWN", "trades_complete": False,
                "error": "Order or complete trade history could not be verified. A missing order is not proof of cancellation."}


async def cancel(intent_id, ledger_path, *, confirm=False, client=None):
    if confirm is not True:
        raise ExecutionError("Explicit cancellation confirmation is required.")
    intent_id = str(UUID(intent_id))
    row = order_store.get(ledger_path, intent_id)
    if _wallet(client) != row["account"]:
        raise ExecutionError("Configured account does not own this intent.")
    if row["phase"] == "PREPARING":
        order_store.transition(ledger_path, intent_id, "ABORTED", expected="PREPARING")
        return {"ok": True, "intent_id": intent_id, "phase": "ABORTED", "message": "Preparation aborted before POST."}
    if not row["order_id"]:
        raise ExecutionError(_no_order_message(row["phase"], intent_id))
    try:
        async with _secure(client) as authenticated:
            order = await authenticated.get_order(order_id=row["order_id"])
            _validate_order(order, row)
            if (str(order.status).upper() in {"CANCELED", "CANCELLED", "EXPIRED", "INVALID"}
                    or row["order_status"] in {"CANCELED", "CANCELLED", "EXPIRED", "INVALID"}):
                return await _reconcile(authenticated, row, ledger_path)
            response = await authenticated.cancel_order(order_id=row["order_id"])
            if row["order_id"] not in response.canceled:
                raise ExecutionError("Cancellation was not confirmed.")
            return await _reconcile(authenticated, row, ledger_path)
    except Exception:
        order_store.transition(ledger_path, intent_id, "UNKNOWN")
        return {"ok": False, "intent_id": intent_id, "phase": "UNKNOWN", "error": "Cancellation or subsequent fill reconciliation could not be verified; inspect this intent again."}


def _no_order_message(phase, intent_id):
    if phase == "REJECTED":
        return "Polymarket refused this order, so no order exists."
    if phase == "ABORTED":
        return "This intent was stopped before anything was sent, so no order exists."
    if phase == "PREPARING":
        return f"Preparation never reached the exchange. Stop it with `trade cancel {intent_id} --confirm`."
    return f"No verified server order ID is recorded. Run `trade recover {intent_id}` to look for the order in your account."


async def _open_matches(client, row):
    """IDs of open orders in the stored market that match every stored field of the intent."""
    found = []
    async for order in _items(client.list_open_orders(market=row["plan"]["order"]["condition_id"]), "list of open orders"):
        try:
            _validate_order(order, {**row, "order_id": str(order.id)})
        except ExecutionError:
            continue
        found.append(str(order.id))
    return found


def _may_belong(trade, row):
    """True when a trade is on the stored token and side and involves the account, so it could be a fill of the intent."""
    order = row["plan"]["order"]
    if str(trade.asset_id) == order["token_id"] and trade.side == order["side"] and str(trade.maker_address).lower() == row["account"]:
        return True
    return any(str(m.asset_id) == order["token_id"] and m.side == order["side"] and str(m.maker_address).lower() == row["account"]
               for m in getattr(trade, "maker_orders", ()))


async def recover(intent_id, order_id, ledger_path, *, client=None):
    """Attach the exchange order to an unresolved intent: by an order ID you verified, or by finding the one matching open order."""
    if order_id is not None and not _ORDER_ID.fullmatch(order_id):
        raise ExecutionError("A server order ID is 0x followed by 64 hex digits.")
    intent_id = str(UUID(intent_id))
    row = order_store.get(ledger_path, intent_id)
    if row["phase"] not in {"SUBMITTING", "UNKNOWN"} or (row["order_id"] and order_id and row["order_id"] != order_id):
        raise ExecutionError("Only the same unresolved intent can be recovered.")
    if _wallet(client) != row["account"]:
        raise ExecutionError("Configured account does not own this intent.")
    try:
        async with _secure(client) as authenticated:
            order_id = order_id or row["order_id"]
            if not order_id:
                found = await _open_matches(authenticated, row)
                if len(found) != 1:
                    raise ExecutionError("No single open order matches this intent." + (" Verify the order in your account and pass --order-id." if found else
                                         f" If its expiration has passed and your account shows no order or fill for it, run `trade resolve {intent_id} --confirm`."))
                order_id = found[0]
            candidate = {**row, "order_id": order_id}
            order = await authenticated.get_order(order_id=order_id)
            _validate_order(order, candidate)
            order_store.transition(ledger_path, intent_id, "UNKNOWN", order_id=order_id)
            return await _reconcile(authenticated, candidate, ledger_path)
    except Exception as error:
        detail = f" {error}" if isinstance(error, ExecutionError) else ""
        return {"ok": False, "intent_id": intent_id, "phase": row["phase"],
                "error": "Recovery could not verify an order and its complete trade history. No order was submitted or retried." + detail}


async def resolve(intent_id, ledger_path, *, confirm=False, now=None, client=None):
    """Close an unresolved intent that never got an order ID, once its GTD order has expired and the account shows no matching order or fill."""
    if confirm is not True:
        raise ExecutionError("Explicit confirmation is required: first check your Polymarket account for any order or fill from this intent.")
    intent_id = str(UUID(intent_id))
    row = order_store.get(ledger_path, intent_id)
    if row["phase"] not in {"SUBMITTING", "UNKNOWN"} or row["order_id"]:
        raise ExecutionError("Only an unresolved intent without a server order ID can be resolved this way.")
    order = row["plan"]["order"]
    now = time.time() if now is None else now
    if now < order["expiration"] + 120:
        raise ExecutionError("The order could still be live. Wait until two minutes after its expiration time.")
    if _wallet(client) != row["account"]:
        raise ExecutionError("Configured account does not own this intent.")
    try:
        async with _secure(client) as authenticated:
            if await _open_matches(authenticated, row):
                raise ExecutionError(f"An open order still matches this intent; run `trade recover {intent_id}`.")
            async for trade in _items(authenticated.list_account_trades(market=order["condition_id"], after=str(int(row["created_at"] - 60))), "trade history"):
                if _may_belong(trade, row):
                    raise ExecutionError(f"Trade {trade.id} may be a fill of this intent; find its order ID in your account and run `trade recover {intent_id} --order-id ...`.")
    except ExecutionError:
        raise
    except Exception:
        raise ExecutionError("The account could not be checked, so the intent stays unresolved.") from None
    effective = order_store.transition(ledger_path, intent_id, "ABORTED", expected=row["phase"], order_status="NOT_PLACED")
    return {"ok": True, "intent_id": intent_id, "phase": effective["phase"], "order_status": effective["order_status"],
            "message": "No matching order or fill was found after expiration; this intent is closed and the account is unblocked."}


def local_summary(ledger_path):
    return {**order_store.summary(ledger_path), "fee_notice": "Stored fill fees are estimates, never actual fee receipts."}
