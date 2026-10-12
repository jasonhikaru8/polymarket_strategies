"""Every forecast-capable indexed method through actual preview, POST and fill tracking."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from types import SimpleNamespace as NS

import pytest

from polymarket_strategies import execution, strategy_catalog as catalog, strategy_cli, trade_plan, trading_cli
from helpers import as_if_real
from test_trading_workflows import NOW, SyntheticClient, offline


INDICES = [row[0] for row in catalog.STRATEGIES if row[-1] == "forecast_order"]


def world(monkeypatch, parameters, index):
    """The synthetic market and client that match a strategy's made-up inputs."""
    if index == 33:
        parameters["poll_cost"] = 0.05  # a made-up small allocated expense for this five-share fixture
    client = SyntheticClient("model_value")
    client.market.resolution.source = parameters["resolution_source"]
    client.market.description = parameters["target_yes_definition"]
    client.market.state.end_date = datetime.fromtimestamp(parameters["contract"]["end_time"], timezone.utc)
    client.book.asset_id = str(client.market.outcomes.yes.token_id if parameters["outcome"] == "YES" else client.market.outcomes.no.token_id)
    client.book.asks[0].price = Decimal(str(parameters["limit_price"]))
    client.book.bids[0].price = client.book.asks[0].price - Decimal("0.01")
    monkeypatch.setattr(trade_plan, "AsyncPublicClient", lambda: client)
    return client


@pytest.mark.parametrize("index", INDICES)
def test_indexed_decision_to_confirmed_fill_integration(offline, index):
    monkeypatch, ledger = offline
    parameters = catalog.example(index, now=NOW)
    parameters.pop("demo")  # synthetic fixture deliberately exercises the order branch, never an account
    with pytest.raises(ValueError, match="placeholder"):
        strategy_cli.prepare(index, parameters, {})  # the example's placeholder text alone keeps it from becoming an order plan
    parameters = as_if_real(parameters)
    client = world(monkeypatch, parameters, index)

    async def workflow():
        inspected = await trade_plan.inspect(client.market.slug, client)
        base = trade_plan.draft_config(inspected, now=NOW)
        base.update(outcome=parameters["outcome"], limit_price=str(parameters["limit_price"]))
        base["limits"].update(max_cash="10", max_shares="5")
        config = strategy_cli.prepare(index, parameters, base, min_edge=parameters["min_edge"], now=NOW)
        config["approval"].update(approved=True, yes_definition=parameters["target_yes_definition"],
                                  note="Offline synthetic full-rule approval only.")
        preview = await trade_plan.preview(config)
        assert preview["eligible"], preview["reasons"]
        assert preview["decision"]["strategy"]["index"] == index
        assert preview["decision"]["edge_per_share"] >= config["strategy"]["min_edge"]
        posted = await execution.submit(config, ledger, confirm=preview["plan_id"], live=True, client=client)
        assert posted["ok"] and posted["phase"] == "ACCEPTED"
        status = await execution.status(config["intent_id"], ledger, client=client)
        assert status["ok"] and status["confirmed_filled_shares"] == "5"
        assert Decimal(status["current_outcome_holdings"]) == Decimal("5")
        assert status["pending_filled_shares"] == "0" and status["trades_complete"]

    asyncio.run(workflow())
    assert client.calls.count("sign") == 1 and client.calls.count("post") == 1


@pytest.mark.parametrize("index", INDICES)
def test_the_terminal_approval_completes_a_prepared_strategy_order(offline, tmp_path, index):
    """`trade approve` (Enter keeps the strategy's own YES definition) is all a prepared config needs to preview as eligible."""
    monkeypatch, _ = offline
    parameters = catalog.example(index, now=NOW)
    parameters.pop("demo")
    parameters = as_if_real(parameters)
    client = world(monkeypatch, parameters, index)
    monkeypatch.setattr(trading_cli, "time", NS(time=lambda: NOW))
    monkeypatch.setattr(trading_cli.sys.stdin, "isatty", lambda: True)
    answers = iter(["", "Offline synthetic full-rule approval only.", "APPROVE"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    async def workflow():
        inspected = await trade_plan.inspect(client.market.slug, client)
        base = trade_plan.draft_config(inspected, now=NOW, outcome=parameters["outcome"], shares="5",
                                       limit_price=str(parameters["limit_price"]), max_cash="10")
        config = strategy_cli.prepare(index, parameters, base, min_edge=parameters["min_edge"], now=NOW)
        path = tmp_path / "trade.json"
        path.write_text(json.dumps(config))
        assert not (await trade_plan.preview(config))["eligible"]  # prepared, not yet approved
        await trading_cli.approve(str(path), 60)
        preview = await trade_plan.preview(json.loads(path.read_text()))
        assert preview["eligible"], preview["reasons"]
        assert preview["decision"]["strategy"]["index"] == index

    asyncio.run(workflow())
