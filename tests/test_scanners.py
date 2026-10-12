"""Scanner logic on synthetic order books: no network needed."""
from types import SimpleNamespace as NS

import pytest

from polymarket_strategies import baskets, constraint_scan, data, fees, negrisk_scan, parity_scan, wallet_audit

FREE = fees.FeeSchedule(rate=0.0)
POLITICS = fees.schedule_for("politics")


def book(asks=(), bids=()):
    return NS(asks=[NS(price=p, size=s) for p, s in asks], bids=[NS(price=p, size=s) for p, s in bids])


def test_walk_stops_when_the_next_level_is_not_profitable():
    # YES asks 0.40 x10 then 0.55; NO asks 0.50 x6 then 0.55. First 6 sets cost 0.90, next 4 cost 0.95, then 1.10 (stop).
    res = baskets.walk([[(0.40, 10), (0.55, 10)], [(0.50, 6), (0.55, 10)]], baskets.buy_basket_profit([FREE, FREE]))
    assert res["sets"] == pytest.approx(10)
    assert res["profit"] == pytest.approx(6 * 0.10 + 4 * 0.05)
    # a second NO level priced at 0.60 makes the next basket cost exactly $1.00: no profit, so the walk stops at 6
    flat = baskets.walk([[(0.40, 10)], [(0.50, 6), (0.60, 10)]], baskets.buy_basket_profit([FREE, FREE]))
    assert flat["sets"] == pytest.approx(6)


def test_fees_can_erase_a_visible_gap():
    tight = [[(0.495, 100)], [(0.495, 100)]]  # 1c gap before fees
    assert baskets.walk(tight, baskets.buy_basket_profit([FREE, FREE]))["sets"] == 100
    assert baskets.walk(tight, baskets.buy_basket_profit([fees.schedule_for("crypto")] * 2))["sets"] == 0


def test_parity_buy_and_mint_sides():
    cheap = parity_scan.scan_pair(book(asks=[(0.45, 20)]), book(asks=[(0.50, 20)]), FREE)
    assert cheap["buy_pair"]["sets"] == 20 and cheap["buy_pair"]["placeable"] is True
    rich = parity_scan.scan_pair(book(bids=[(0.55, 3)]), book(bids=[(0.50, 3)]), FREE)
    assert rich["mint_and_sell"]["sets"] == 3 and rich["mint_and_sell"]["placeable"] is False  # under the 5-share minimum
    fair = parity_scan.scan_pair(book(asks=[(0.50, 50)], bids=[(0.49, 50)]), book(asks=[(0.51, 50)], bids=[(0.48, 50)]), POLITICS)
    assert fair["buy_pair"]["sets"] == 0 and fair["mint_and_sell"]["sets"] == 0


def test_negrisk_baskets_and_placeholder_flag():
    def market(label, tokens):
        return NS(group_item_title=label, question=label, trading=NS(fees_enabled=False), outcomes=None, _tokens=tokens)
    labels = ["Alice", "Bob", "Carol"]
    assert negrisk_scan.looks_augmented(["Alice", "Other"]) and negrisk_scan.looks_augmented(["Person A", "Bob"])
    assert not negrisk_scan.looks_augmented(labels)
    yes_asks = [[(0.30, 10)], [(0.30, 10)], [(0.30, 10)]]  # sums to 0.90
    res = baskets.walk(yes_asks, baskets.buy_basket_profit([FREE] * 3, 1.0))
    assert res["sets"] == 10 and res["profit"] == pytest.approx(1.0)
    no_asks = [[(0.70, 10)], [(0.70, 10)], [(0.70, 10)]]  # 2.10 for a payout of n-1 = 2
    assert baskets.walk(no_asks, baskets.buy_basket_profit([FREE] * 3, 2.0))["sets"] == 0


def test_wallet_audit_flags_bond_style_and_thin_records():
    trades = [{"side": "BUY", "size": 100, "price": 0.97, "event": f"e{i}"} for i in range(10)]
    positions = [{"total_pnl": 3.0}] * 9 + [{"total_pnl": -97.0}]
    out = wallet_audit.audit(trades, positions)
    assert out["distinct_events"] == 10 and out["share_of_buy_dollars_ge_90c"] == 1.0
    assert out["net_pnl"] == -70.0  # nine wins of +3 and one loss of -97
    assert any("90c or more" in f for f in out["flags"]) and any("fewer than 100 distinct events" in f for f in out["flags"])
    assert out["profit_factor"] < 1


def market(slug, minimum=5, label=None):
    return NS(slug=slug, question=slug, group_item_title=label or slug, version="v1",
              state=NS(accepting_orders=True, enable_order_book=True, neg_risk=True),
              trading=NS(fees_enabled=False, minimum_order_size=minimum),
              outcomes=NS(yes=NS(token_id=slug + "-yes"), no=NS(token_id=slug + "-no")))


def fake_client(monkeypatch, module, markets, books, events=()):
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
            return Pages(markets)

        def list_events(self, **kwargs):
            return Pages(events)

    async def frozen_books(client, tokens):
        return books

    monkeypatch.setattr(module, "AsyncPublicClient", Client)
    monkeypatch.setattr(module, "books_by_token", frozen_books)


@pytest.mark.parametrize("size,expected", [(3, False), (5, True)])
def test_parity_hits_exclude_profitable_depth_below_minimum(monkeypatch, size, expected):
    import asyncio
    m = market("pair")
    books = {"pair-yes": book(asks=[(0.4, size)]), "pair-no": book(asks=[(0.5, size)])}
    fake_client(monkeypatch, parity_scan, [m], books)
    scanned, hits, near = asyncio.run(parity_scan.run(1))
    assert scanned == 1 and bool(hits) is expected


@pytest.mark.parametrize("size,expected", [(5, False), (8, True)])
def test_negrisk_hits_use_the_largest_leg_minimum(monkeypatch, size, expected):
    import asyncio
    markets = [market("a", 5), market("b", 8), market("c", 5)]
    books = {m.slug + side: book(asks=[(price, size)]) for m in markets for side, price in (("-yes", 0.3), ("-no", 0.7))}
    event = NS(markets=markets, slug="event", title="event", trading=NS(neg_risk_augmented=False))
    raw = negrisk_scan.scan_event(markets, books)
    assert raw["buy_all_yes"]["sets"] == size and raw["buy_all_yes"]["placeable"] is expected
    fake_client(monkeypatch, negrisk_scan, markets, books, [event])
    scanned, hits = asyncio.run(negrisk_scan.run(1))
    assert scanned == 1 and bool(hits) is expected


def test_constraints_report_profitable_but_unplaceable_depth(monkeypatch):
    import asyncio
    markets = [market("small", 8), market("large", 5)]
    books = {"large-yes": book(asks=[(0.4, 5)]), "large-no": book(),
             "small-yes": book(), "small-no": book(asks=[(0.5, 5)])}
    fake_client(monkeypatch, constraint_scan, markets, books)
    rows = asyncio.run(constraint_scan.run([{"smaller": "small", "larger": "large"}]))
    assert rows[0]["sets"] == 5 and rows[0]["profit"] > 0 and rows[0]["placeable"] is False


@pytest.mark.parametrize("yes_id,no_id", [(None, "no"), ("yes", None), (" ", "no"), ("same", "same")])
def test_binary_tokens_require_two_distinct_nonempty_ids(yes_id, no_id):
    m = market("invalid")
    m.outcomes.yes.token_id, m.outcomes.no.token_id = yes_id, no_id
    assert data.yes_no_tokens(m) is None


@pytest.mark.parametrize("field", ["accepting_orders", "enable_order_book"])
@pytest.mark.parametrize("value", [False, None])
def test_scanners_reject_unavailable_market_legs(monkeypatch, field, value):
    import asyncio

    markets = [market(slug) for slug in ("a", "b", "c", "d")]
    setattr(markets[0].state, field, value)
    books = {m.slug + side: book(asks=[(price, 10)])
             for m in markets for side, price in (("-yes", 0.3), ("-no", 0.6))}
    fake_client(monkeypatch, parity_scan, markets[:1], books)
    assert asyncio.run(parity_scan.run(1))[:2] == (0, [])

    event = NS(markets=markets, slug="event", title="event", trading=NS(neg_risk_augmented=False))
    fake_client(monkeypatch, negrisk_scan, markets, books, [event])
    assert asyncio.run(negrisk_scan.run(1)) == (0, [])  # do not shrink the four-outcome universe

    fake_client(monkeypatch, constraint_scan, markets, books)
    rows = asyncio.run(constraint_scan.run([{"smaller": "a", "larger": "b"}]))
    assert "error" in rows[0] and "placeable" not in rows[0]


@pytest.mark.parametrize("augmented", [True, None])
def test_negrisk_excludes_augmented_or_unknown_events_despite_ordinary_labels(monkeypatch, augmented):
    import asyncio

    markets = [market(name) for name in ("Alice", "Bob", "Carol")]
    books = {m.slug + side: book(asks=[(price, 10)])
             for m in markets for side, price in (("-yes", 0.3), ("-no", 0.7))}
    event = NS(markets=markets, slug="event", title="event",
               trading=NS(enable_neg_risk=True, neg_risk_augmented=augmented))
    fake_client(monkeypatch, negrisk_scan, markets, books, [event])
    assert asyncio.run(negrisk_scan.run(1)) == (0, [])


def test_missing_constraint_book_does_not_abort_other_pairs(monkeypatch):
    import asyncio

    markets = [market(slug) for slug in ("a", "b", "c")]
    books = {"b-yes": book(asks=[(0.3, 10)]), "c-no": book(asks=[(0.6, 10)])}
    fake_client(monkeypatch, constraint_scan, markets, books)
    rows = asyncio.run(constraint_scan.run([{"smaller": "a", "larger": "b"}, {"smaller": "c", "larger": "b"}]))
    assert "error" in rows[0] and "placeable" not in rows[0]
    assert rows[1]["placeable"] is True and rows[1]["profit"] == pytest.approx(1.0)


def test_negrisk_skips_incomplete_books_without_shrinking_the_bundle(monkeypatch):
    import asyncio

    markets = [market(slug) for slug in ("a", "b", "c", "d")]
    books = {m.slug + side: book(asks=[(price, 10)])
             for m in markets[:3] for side, price in (("-yes", 0.3), ("-no", 0.7))}
    event = NS(markets=markets, slug="event", title="event", trading=NS(neg_risk_augmented=False))
    fake_client(monkeypatch, negrisk_scan, markets, books, [event])
    assert asyncio.run(negrisk_scan.run(1)) == (0, [])


@pytest.mark.parametrize("fees_enabled", [True, None])
def test_scanners_cannot_establish_profit_with_unknown_fees(monkeypatch, fees_enabled):
    import asyncio

    markets = [market(slug) for slug in ("a", "b", "c")]
    markets[0].trading = NS(fees_enabled=fees_enabled, fee_schedule=None, minimum_order_size=5)
    books = {m.slug + side: book(asks=[(price, 10)])
             for m in markets for side, price in (("-yes", 0.3), ("-no", 0.6))}
    fake_client(monkeypatch, parity_scan, markets[:1], books)
    assert asyncio.run(parity_scan.run(1))[:2] == (0, [])
    event = NS(markets=markets, slug="event", title="event", trading=NS(neg_risk_augmented=False))
    fake_client(monkeypatch, negrisk_scan, markets, books, [event])
    assert asyncio.run(negrisk_scan.run(1)) == (0, [])
    fake_client(monkeypatch, constraint_scan, markets, books)
    rows = asyncio.run(constraint_scan.run([{"smaller": "a", "larger": "b"}]))
    assert "error" in rows[0] and "placeable" not in rows[0]


def test_parity_scan_says_what_it_read_and_what_it_skipped(monkeypatch, capsys):
    import asyncio
    good, closed_book = market("good"), market("shut")
    closed_book.state.accepting_orders = False
    no_books = market("nobooks")
    unknown_fees = market("fees")
    unknown_fees.trading = NS(fees_enabled=None, minimum_order_size=5)
    books = {"good-yes": book(asks=[(0.5, 50)]), "good-no": book(asks=[(0.52, 50)]),
             "fees-yes": book(asks=[(0.5, 50)]), "fees-no": book(asks=[(0.5, 50)])}
    fake_client(monkeypatch, parity_scan, [good, closed_book, no_books, unknown_fees], books)
    notes = {}
    scanned, _, _ = asyncio.run(parity_scan.run(10, notes))
    assert scanned == 1 and notes == {"read": 4, "not_tradable": 1, "no_book": 1, "unknown_fees": 1}
    fake_client(monkeypatch, parity_scan, [good, closed_book, no_books, unknown_fees], books)
    parity_scan.main(["--limit", "10"])
    err = capsys.readouterr().err
    assert "Read the 4 open markets" in err and "1 were not accepting orders" in err and "1 without an order book" in err and "1 with an unknown fee" in err


def test_parity_scan_reads_a_full_page_so_the_limit_counts_tradable_markets(monkeypatch):
    import asyncio
    seen = {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def list_markets(self, **kwargs):
            seen.update(kwargs)
            return NS(first_page=lambda: _empty_page())

    async def _empty_page():
        return NS(items=[])

    async def frozen_books(client, tokens):
        return {}
    monkeypatch.setattr(parity_scan, "AsyncPublicClient", Client)
    monkeypatch.setattr(parity_scan, "books_by_token", frozen_books)
    asyncio.run(parity_scan.run(7))
    assert seen["page_size"] == 100  # not min(limit, 100): the filter runs after the fetch


@pytest.mark.parametrize("module", [parity_scan, negrisk_scan])
@pytest.mark.parametrize("limit", ["0", "-1", "101", "500"])
def test_scan_limits_outside_one_page_are_refused_instead_of_silently_capped(module, limit, capsys):
    with pytest.raises(SystemExit) as failure:
        module.main(["--limit", limit])
    assert failure.value.code == 2 and "between 1 and 100" in capsys.readouterr().err


def test_negrisk_scan_says_what_it_read_and_skipped(monkeypatch, capsys):
    import asyncio
    markets = [market("a"), market("b"), market("c")]
    books = {m.slug + side: book(asks=[(price, 50)]) for m in markets for side, price in (("-yes", 0.5), ("-no", 0.7))}
    event = NS(markets=markets, slug="event", title="event", trading=NS(neg_risk_augmented=False))
    augmented = NS(markets=markets, slug="aug", title="aug", trading=NS(neg_risk_augmented=True))
    two_way = NS(markets=markets[:2], slug="two", title="two", trading=NS(neg_risk_augmented=False))
    fake_client(monkeypatch, negrisk_scan, markets, books, [event, augmented, two_way])
    notes = {}
    assert asyncio.run(negrisk_scan.run(5, notes))[0] == 1
    assert notes == {"read": 3, "not_eligible": 2, "no_book": 0, "unscannable": 0}
    fake_client(monkeypatch, negrisk_scan, markets, books, [event, augmented, two_way])
    negrisk_scan.main(["--limit", "5"])
    assert "Read the 3 open events" in capsys.readouterr().err


def test_constraint_scan_reads_more_than_one_hundred_slugs_in_batches(monkeypatch):
    import asyncio
    requested = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def list_markets(self, **kwargs):
            requested.append(kwargs["slug"])
            found = [market(slug) for slug in kwargs["slug"]]

            async def first_page():
                assert len(kwargs["slug"]) <= 100
                return NS(items=found)
            return NS(first_page=first_page)

    async def frozen_books(client, tokens):
        return {}
    monkeypatch.setattr(constraint_scan, "AsyncPublicClient", Client)
    monkeypatch.setattr(constraint_scan, "books_by_token", frozen_books)
    pairs = [{"smaller": f"s{i}", "larger": f"l{i}"} for i in range(70)]  # 140 distinct slugs
    rows = asyncio.run(constraint_scan.run(pairs))
    assert [len(chunk) for chunk in requested] == [100, 40]
    assert len(rows) == 70 and all(row["error"] == "required order book is unavailable" for row in rows)  # every market was found


def test_exact_dollar_baskets_with_deep_books_are_not_profit_from_round_off():
    """0.01 + 0.29 + 0.70 is exactly $1.00 in dollars; float arithmetic gave +1.1e-16 a set, which 100,000 sets of depth turned into 'placeable'."""
    legs = [[(0.01, 100_000)], [(0.29, 100_000)], [(0.7, 100_000)]]
    assert baskets.walk(legs, baskets.buy_basket_profit([FREE] * 3), min_size=5)["placeable"] is False
    real = [[(0.01, 100_000)], [(0.29, 100_000)], [(0.699, 100_000)]]  # a tenth of a cent a set is a real profit
    assert baskets.walk(real, baskets.buy_basket_profit([FREE] * 3), min_size=5)["placeable"] is True


def test_the_wallet_audit_flag_for_late_copying_needs_over_half_of_the_dollars_at_90_cents_or_more():
    def trades(late, early):
        return ([{"side": "BUY", "size": 100, "price": 0.95, "event": f"l{i}"} for i in range(late)]
                + [{"side": "BUY", "size": 100, "price": 0.50, "event": f"e{i}"} for i in range(early)])
    positions = [{"total_pnl": 1.0}]
    mostly_late = wallet_audit.audit(trades(6, 4), positions)  # 570 of 770 dollars at 0.95: 74%
    assert any("90c or more" in flag for flag in mostly_late["flags"]) and mostly_late["share_of_buy_dollars_ge_90c"] == pytest.approx(0.74, abs=0.001)
    mostly_early = wallet_audit.audit(trades(3, 7), positions)  # 285 of 635 dollars: 45%
    assert not any("90c or more" in flag for flag in mostly_early["flags"])


@pytest.mark.parametrize("value", [False, None])
def test_the_negrisk_scan_needs_every_outcome_market_to_be_neg_risk(monkeypatch, value):
    import asyncio

    markets = [market(slug) for slug in ("a", "b", "c", "d")]
    markets[0].state.neg_risk = value
    books = {m.slug + side: book(asks=[(price, 10)]) for m in markets for side, price in (("-yes", 0.3), ("-no", 0.6))}
    event = NS(markets=markets, slug="event", title="event", trading=NS(neg_risk_augmented=False))
    fake_client(monkeypatch, negrisk_scan, markets, books, [event])
    assert asyncio.run(negrisk_scan.run(1)) == (0, [])  # nothing scanned: the event is not a NegRisk universe


# ---- Polymarket unreachable: one plain line and exit status 1, never a traceback (simulated offline at the transport)
@pytest.fixture
def unreachable(monkeypatch):
    """Polymarket refused, as behind a proxy that denies it: the SDK's httpx client and urllib's plain requests both fail."""
    import urllib.error
    import urllib.request

    import httpx

    async def refuse(self, request, **kwargs):
        raise httpx.ConnectError("403 Forbidden", request=request)

    def refuse_urlopen(*args, **kwargs):
        raise urllib.error.URLError("Tunnel connection failed: 403 Forbidden")

    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse_urlopen)


PUBLIC_COMMANDS = (["parity-scan", "--limit", "5"], ["negrisk-scan", "--limit", "5"], ["constraint-scan", "CONSTRAINTS"],
                   ["resolution-watch", "some-market-slug"], ["resolution-watch", "--disputed"],
                   ["wallet-audit", "0x" + "ab" * 20], ["calc", "--slug", "some-market-slug", "--price", "0.5"])


@pytest.mark.parametrize("argv", PUBLIC_COMMANDS, ids=" ".join)
def test_a_public_tool_that_cannot_reach_polymarket_prints_one_plain_line(argv, unreachable, tmp_path, capsys):
    from polymarket_strategies.__main__ import main

    constraints = tmp_path / "constraints.json"
    constraints.write_text('[{"smaller": "smaller-slug", "larger": "larger-slug"}]')
    argv = [str(constraints) if arg == "CONSTRAINTS" else arg for arg in argv]
    with pytest.raises(SystemExit) as failure:
        main(argv)
    assert failure.value.code == 1
    out, err = capsys.readouterr()
    assert out == "" and err.count("\n") == 1
    assert err.startswith(f"{argv[0]}: could not read Polymarket's public data (") and "403 Forbidden" in err
    assert "placed no order" in err and "Traceback" not in err


def test_a_refusal_from_polymarket_itself_is_one_plain_line_too(monkeypatch, capsys):
    import httpx

    async def unavailable(self, request, **kwargs):
        return httpx.Response(503, request=request, json={"error": "service unavailable"})

    monkeypatch.setattr(httpx.AsyncClient, "send", unavailable)
    with pytest.raises(SystemExit) as failure:
        parity_scan.main(["--limit", "5"])
    assert failure.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("parity-scan: could not read Polymarket's public data (HTTP 503") and err.count("\n") == 1


@pytest.mark.parametrize("address", ["0xYOUR_WALLET_OF_INTEREST", "0x...", "YOUR_PUBLIC_ADDRESS", "0x" + "a" * 39,
                                     "0x" + "a" * 41, "0x" + "g" * 40, " 0x" + "a" * 40])
def test_wallet_audit_checks_the_address_before_any_request(address, monkeypatch, capsys):
    class NoRequests:
        def __init__(self, *args, **kwargs):
            raise AssertionError("an invalid address must not reach the network")

    monkeypatch.setattr(wallet_audit, "AsyncPublicClient", NoRequests)
    with pytest.raises(SystemExit) as failure:
        wallet_audit.main([address])
    assert failure.value.code == 2
    assert "0x followed by 40 hexadecimal characters" in capsys.readouterr().err


def test_wallet_audit_sends_a_well_formed_address(monkeypatch, capsys):
    seen = []

    async def run(wallet, limit):
        seen.append(wallet)
        return {"distinct_events": 0}

    monkeypatch.setattr(wallet_audit, "run", run)
    address = "0x" + "0123456789abcdefABCD" * 2
    wallet_audit.main([address])
    assert seen == [address] and '"distinct_events": 0' in capsys.readouterr().out
