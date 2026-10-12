"""Money and contract boundaries on synthetic public data; no account or network."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from polymarket_strategies import trade_plan

NOW = 1_800_000_000


def fixture():
    contract = {"slug": "synthetic-contract", "condition_id": "condition", "question": "Synthetic question?",
                "description": "Synthetic full rules", "resolution_source": "https://example.com/source",
                "end_time": NOW + 86400 * 30, "tokens": {"YES": "123", "NO": "456"},
                "neg_risk": False, "version": "v1"}
    state = {"active": True, "closed": False, "archived": False, "accepting_orders": True,
             "enable_order_book": True, "uma_status": None}
    inspected = {"contract": contract, "state": state, "fingerprint": trade_plan.digest(contract),
                 "market": NS(trading=NS(fees_enabled=True,
                                        fee_schedule=NS(rate=0.04, exponent=1, rebate_rate=0, taker_only=True)))}
    config = trade_plan.draft_config(inspected, now=NOW)
    config["limits"].update(max_cash="10", max_shares="10")
    config["approval"].update(approved=True, yes_definition="Exact reviewed YES event", note="Read all rules")
    book = NS(asset_id="123", condition_id="condition", neg_risk=False, timestamp=datetime.fromtimestamp(NOW, timezone.utc),
              asks=[NS(price=Decimal("0.49"), size=Decimal("3")), NS(price=Decimal("0.50"), size=Decimal("4"))],
              bids=[NS(price=Decimal("0.48"), size=Decimal("10"))], tick_size=Decimal("0.01"), min_order_size=Decimal("5"))
    return config, inspected, book


def test_preview_reports_actual_depth_and_conservative_cash_reserve():
    config, inspected, book = fixture()
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert result["eligible"] is True
    assert result["quote"]["immediately_available_shares"] == "5"
    assert Decimal(result["quote"]["displayed_average_price"]) == Decimal("0.494")
    assert Decimal(result["cash_bound"]) >= Decimal("2.55")
    assert result["decision"]["probability"] is None


@pytest.mark.parametrize("key,value", [
    ("shares", "NaN"), ("shares", "-1"), ("shares", "4"), ("shares", "5.001"),
    ("limit_price", "0.505"), ("limit_price", "Infinity"), ("limit_price", True),
    ("outcome", "UP"), ("side", "SHORT"), ("expires_at", NOW + 180), ("expires_at", NOW + 4000),
    ("post_only", "false"), ("intent_id", "not-a-uuid"),
])
def test_invalid_plan_never_becomes_eligible(key, value):
    config, inspected, book = fixture()
    config[key] = value
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert not result["eligible"] and result["reasons"]


def reseal(config, inspected, **changes):
    """Change the public contract and re-approve its new fingerprint, so only the changed field can be the reason for a refusal."""
    inspected["contract"].update(changes)
    inspected["fingerprint"] = trade_plan.digest(inspected["contract"])
    config["approval"]["fingerprint"] = inspected["fingerprint"]


@pytest.mark.parametrize("mutation", [
    lambda c, i, b: c["approval"].update(approved=False),
    lambda c, i, b: c["approval"].update(fingerprint="wrong"),
    lambda c, i, b: c["approval"].update(yes_definition=""),
    lambda c, i, b: c["approval"].update(valid_until=NOW + 600),
    lambda c, i, b: c["limits"].update(max_cash="2.50"),
    lambda c, i, b: c["limits"].update(max_shares="4"),
    lambda c, i, b: c["limits"].update(max_quote_age_seconds=121),
    lambda c, i, b: i["state"].update(accepting_orders=None),
    lambda c, i, b: i["state"].update(uma_status="disputed"),
    lambda c, i, b: setattr(b, "neg_risk", True),
    lambda c, i, b: setattr(b, "timestamp", datetime.fromtimestamp(NOW - 31, timezone.utc)),
    lambda c, i, b: setattr(b, "timestamp", None),
    lambda c, i, b: setattr(b, "asset_id", "456"),
    lambda c, i, b: setattr(b, "condition_id", "other-contract"),
    lambda c, i, b: setattr(i["market"].trading, "fee_schedule", None),
    lambda c, i, b: setattr(i["market"].trading.fee_schedule, "taker_only", False),
    lambda c, i, b: c.update(post_only=True),
    lambda c, i, b: c["approval"].update(approved="true"),  # only the boolean True approves
    lambda c, i, b: c["approval"].update(approved=1),
    lambda c, i, b: c["approval"].update(approved="false"),
    lambda c, i, b: setattr(b, "timestamp", datetime.fromtimestamp(NOW + 60, timezone.utc)),  # a book from the future
    lambda c, i, b: c["approval"].update(valid_until=NOW + 86401),  # an approval may last 24 hours at most
    lambda c, i, b: c["approval"].update(reviewed_at=NOW + 60, valid_until=NOW + 3600),  # reviewed in the future
    lambda c, i, b: c["approval"].update(resolution_source="https://other.example/rules"),  # not the contract's own source
    lambda c, i, b: c["approval"].update(note=""),
    lambda c, i, b: c.update(market_slug="some-other-contract"),
    lambda c, i, b: i["state"].update(archived=True),
    lambda c, i, b: i["state"].update(enable_order_book=False),
    lambda c, i, b: reseal(c, i, version="v3"),  # a protocol version this toolkit does not know
    lambda c, i, b: reseal(c, i, end_time=NOW + 300),  # the order would outlive the market
])
def test_unapproved_stale_missing_or_over_budget_data_blocks_orders(mutation):
    config, inspected, book = fixture()
    mutation(config, inspected, book)
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert not result["eligible"] and result["reasons"]


def test_larger_ask_does_not_raise_limit_or_pretend_to_fill():
    config, inspected, book = fixture()
    book.asks = [NS(price=Decimal("0.60"), size=Decimal("100"))]
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert result["eligible"]
    assert result["order"]["price"] == "0.50"
    assert result["quote"]["immediately_available_shares"] == "0"


def test_manual_sell_reserves_shares_and_has_no_invented_forecast():
    config, inspected, book = fixture()
    config.update(side="SELL", limit_price="0.48")
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert result["eligible"] and result["cash_bound"] == "0"
    assert result["order"]["side"] == "SELL"


def test_order_cannot_outlive_forecast():
    config, inspected, book = fixture()
    config["strategy"] = {"kind": "model_value", "min_edge": 0.02, "inputs": {
        "probability_yes": 0.7, "conservative_low_yes": 0.6, "conservative_high_yes": 0.8,
        "as_of": NOW, "valid_until": NOW + 600, "target_yes_definition": config["approval"]["yes_definition"],
        "resolution_source": config["approval"]["resolution_source"], "evidence": "Synthetic only", "source_notes": "No real data"}}
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert not result["eligible"] and "forecast expires" in result["reasons"][0]


def test_plan_confirmation_changes_when_economic_config_changes():
    config, inspected, book = fixture()
    before = trade_plan.build_preview(config, inspected, book, now=NOW)
    config["shares"] = "6"
    after = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert before["plan_id"] != after["plan_id"]


def test_public_preview_never_creates_a_secure_client(monkeypatch):
    from polymarket import AsyncSecureClient
    config, inspected, book = fixture()
    async def reject_auth(*args, **kwargs):
        pytest.fail("Preview attempted authentication")
    async def inspect(*args):
        return inspected
    monkeypatch.setattr(AsyncSecureClient, "create", reject_auth)
    monkeypatch.setattr(trade_plan, "inspect", inspect)
    class Public:
        async def get_order_book(self, **kwargs):
            return book
    assert asyncio.run(trade_plan.preview(config, Public(), now=NOW))["eligible"]


def test_cli_rejects_nonfinite_json_and_credentials_in_config(tmp_path):
    from polymarket_strategies.trading_cli import load_config
    path = tmp_path / "config.json"
    path.write_text('{"shares": NaN}')
    with pytest.raises(ValueError):
        load_config(str(path))
    path.write_text('{"private_key": "DO-NOT-STORE-KEYS"}')
    with pytest.raises(ValueError):
        load_config(str(path))


V1_YES, V1_NO = str(1 << 40), str((1 << 40) + 1)  # synthetic V1 token IDs: real ones are large hashes, and small numbers sit in the V2 position-ID range


def market(labels=("Yes", "No"), end_date=datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc)):
    """The attributes `contract_of` reads, on a stand-in for the SDK's market object."""
    return NS(slug="stand-in", condition_id="condition", question="Stand-in question?", description="Stand-in rules",
              version="v1", resolution=NS(source="https://sources.test/rules"),
              state=NS(end_date=end_date, neg_risk=False),
              outcomes=NS(yes=NS(token_id=V1_YES, label=labels[0]), no=NS(token_id=V1_NO, label=labels[1])))


@pytest.mark.parametrize("labels", [("Yes", "No"), ("yes", "NO"), (" Yes ", "No")])
def test_a_market_labeled_yes_and_no_is_accepted_and_the_labels_are_fingerprinted(labels):
    contract = trade_plan.contract_of(market(labels))
    assert contract["tokens"] == {"YES": V1_YES, "NO": V1_NO} and contract["labels"] == {"YES": labels[0], "NO": labels[1]}


@pytest.mark.parametrize("labels", [("Team A", "Team B"), ("No", "Yes"), ("Up", "Down"), ("Over", "Under"), ("Yes", "Down"), ("Yes", "Yes"), ("Yes", "Under")])
def test_a_market_whose_outcomes_are_not_yes_and_no_is_refused(labels):
    with pytest.raises(ValueError, match="labeled Yes and No"):
        trade_plan.contract_of(market(labels))


def test_a_deadline_without_a_time_zone_is_read_as_utc_on_any_computer(monkeypatch):
    monkeypatch.setenv("TZ", "Pacific/Auckland")
    time_module = __import__("time")
    time_module.tzset()
    try:
        naive = trade_plan.contract_of(market(end_date=datetime(2026, 12, 31, 12, 0)))
        aware = trade_plan.contract_of(market(end_date=datetime(2026, 12, 31, 12, 0, tzinfo=timezone.utc)))
    finally:
        monkeypatch.undo()
        time_module.tzset()
    assert naive["end_time"] == aware["end_time"] == datetime(2026, 12, 31, 12, tzinfo=timezone.utc).timestamp()


def test_a_market_whose_yes_and_no_tokens_are_the_same_is_refused():
    same = market()
    same.outcomes.no.token_id = same.outcomes.yes.token_id
    with pytest.raises(ValueError, match="two different outcome IDs"):
        trade_plan.contract_of(same)


STRATEGY = lambda config, probability=0.8, low=0.7, high=0.9, valid=3600: {"kind": "model_value", "min_edge": 0.02, "inputs": {
    "probability_yes": probability, "conservative_low_yes": low, "conservative_high_yes": high,
    "as_of": NOW, "valid_until": NOW + valid, "target_yes_definition": config["approval"]["yes_definition"],
    "resolution_source": config["approval"]["resolution_source"], "evidence": "Synthetic only", "source_notes": "No real data"}}


def test_cash_bound_reserves_the_fee_where_it_peaks_plus_the_five_decimal_buffer():
    config, inspected, book = fixture()
    base = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert base["cash_bound"] == "2.55001"  # 5 shares x 0.50, plus 5 x 0.01 fee (rate 0.04 at 0.50), plus 0.00001
    config["limit_price"] = "0.60"
    high = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert high["cash_bound"] == "3.05001"  # the fee is reserved at 0.50, where it peaks, although the limit is 0.60


def test_the_decision_uses_the_fee_at_the_limit_price_not_at_the_peak():
    config, inspected, book = fixture()
    config["limit_price"] = "0.60"
    config["strategy"] = STRATEGY(config)
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert result["eligible"]
    # conservative 0.70 - limit 0.60 - fee 0.0096 at 0.60 (rate 0.04 x 0.6 x 0.4) - 0.000002 buffer per share
    assert result["decision"]["edge_per_share"] == pytest.approx(0.090398, abs=1e-9)


def test_forecast_strategies_open_buys_only_and_a_sell_must_be_manual():
    config, inspected, book = fixture()
    config.update(side="SELL", limit_price="0.48")
    config["strategy"] = STRATEGY(config)
    result = trade_plan.build_preview(config, inspected, book, now=NOW)
    assert not result["eligible"] and any("manual SELL" in reason for reason in result["reasons"])


# ---- Protocol V2: the market's `version` decides which ID an outcome is traded by
V2_YES, V2_NO = "1001", "1002"  # synthetic position IDs: small numbers sit inside the V2 position-ID range


def with_ids(version, v1=True, v2=True):
    m = market()
    m.version = version
    m.outcomes.yes.token_id, m.outcomes.no.token_id = (V1_YES, V1_NO) if v1 else (None, None)
    m.outcomes.yes.position_id, m.outcomes.no.position_id = (V2_YES, V2_NO) if v2 else (None, None)
    return m


def test_a_v1_market_that_also_carries_position_ids_is_traded_by_its_token_ids():
    assert trade_plan.contract_of(with_ids("v1"))["tokens"] == {"YES": V1_YES, "NO": V1_NO}  # live V1 markets can carry both fields


def test_a_v2_market_is_traded_by_its_position_ids_and_the_fingerprint_follows():
    v2, v1 = trade_plan.contract_of(with_ids("v2")), trade_plan.contract_of(with_ids("v1"))
    assert v2["tokens"] == {"YES": V2_YES, "NO": V2_NO} and v2["version"] == "v2"
    assert trade_plan.digest(v2) != trade_plan.digest(v1)


@pytest.mark.parametrize("m", [
    with_ids("v2", v2=False),                                            # a V2 market without position IDs
    with_ids("v1", v1=False),                                            # a V1 market without token IDs
    with_ids(None), with_ids("v3"),                                      # a missing or unknown version
    (lambda m: (setattr(m.outcomes.yes, "token_id", V2_YES), m)[1])(with_ids("v1")),  # a V1 market whose token ID lies in the V2 range
    (lambda m: (setattr(m.outcomes.yes, "position_id", V1_YES), m)[1])(with_ids("v2")),  # a V2 market whose position ID lies in the V1 range
])
def test_a_market_without_a_matching_id_for_its_version_is_refused(m):
    with pytest.raises(ValueError, match="known protocol version"):
        trade_plan.contract_of(m)
