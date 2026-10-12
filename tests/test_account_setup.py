"""Easy setup: the private credentials file, the readiness check, the terminal approval and inspect's order flags. Local values only."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

from eth_account import Account
import pytest

from polymarket_strategies import account_setup, execution, safety, trade_plan, trading_cli

NOW = 1_800_000_000
NAMES = account_setup.CREDENTIAL_NAMES
KEY = "0x" + "11" * 32
SIGNER = Account.from_key(KEY).address


@pytest.fixture(autouse=True)
def clean_account_environment(monkeypatch):
    for name in (*NAMES, "POLYMARKET_STRATEGIES_LIVE"):
        monkeypatch.delenv(name, raising=False)


def write_saved(lines, mode=0o600):
    path = account_setup.credentials_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    path.chmod(mode)
    return path


def typing(monkeypatch, answers):
    """Answer input() from a list, as the reader would; the terminal looks interactive."""
    monkeypatch.setattr(trading_cli.sys.stdin, "isatty", lambda: True)
    queue = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(queue))


# --- the credentials file ---

def test_saved_values_fill_only_what_the_environment_lacks(monkeypatch):
    write_saved(["# kept private", "POLYMARKET_API_KEY=from-file", "POLYMARKET_API_SECRET=from-file"])
    monkeypatch.setenv("POLYMARKET_API_KEY", "")  # empty counts as unset; the test restores it afterwards
    monkeypatch.setenv("POLYMARKET_API_SECRET", "from-environment")
    assert account_setup.load_saved() == ["POLYMARKET_API_KEY"]
    assert os.environ["POLYMARKET_API_KEY"] == "from-file" and os.environ["POLYMARKET_API_SECRET"] == "from-environment"


def test_a_file_that_other_users_can_read_is_refused():
    write_saved(["POLYMARKET_API_KEY=from-file"], mode=0o644)
    with pytest.raises(ValueError, match="chmod 600"):
        account_setup.load_saved()
    assert "POLYMARKET_API_KEY" not in os.environ


def test_a_link_or_an_unknown_name_is_refused_and_no_value_is_printed(tmp_path):
    path = account_setup.credentials_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "elsewhere.env"
    target.write_text("POLYMARKET_API_KEY=from-file\n")
    target.chmod(0o600)
    path.symlink_to(target)
    with pytest.raises(ValueError, match="regular file"):
        account_setup.read_saved()
    path.unlink()
    write_saved(["POLYMARKET_API_KEY=ok", "MY_OTHER_SECRET=VALUE_MUST_NOT_PRINT"])
    with pytest.raises(ValueError, match="line 2") as error:
        account_setup.read_saved()
    assert "VALUE_MUST_NOT_PRINT" not in str(error.value)


def test_save_writes_a_file_only_you_can_read_and_keeps_the_old_one_if_it_fails(monkeypatch):
    account_setup.save({"POLYMARKET_API_KEY": "first", "POLYMARKET_API_SECRET": "second"})
    path = account_setup.credentials_file()
    assert path.stat().st_mode & 0o777 == 0o600 and path.parent.stat().st_mode & 0o077 == 0
    assert account_setup.read_saved() == {"POLYMARKET_API_KEY": "first", "POLYMARKET_API_SECRET": "second"}
    monkeypatch.setattr(account_setup.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        account_setup.save({"POLYMARKET_API_KEY": "changed"})
    assert account_setup.read_saved()["POLYMARKET_API_KEY"] == "first"
    assert [p.name for p in path.parent.iterdir()] == ["credentials.env"]  # no stray temporary file


def test_account_commands_use_the_saved_file_and_leave_the_environment_clean(monkeypatch):
    write_saved([f"{name}=from-file" for name in NAMES])
    seen = {}

    async def run(args):
        seen.update({name: os.environ.get(name) for name in NAMES})
    monkeypatch.setattr(trading_cli, "run", run)
    trading_cli.main(["status", "00000000-0000-0000-0000-000000000000"])
    assert set(seen.values()) == {"from-file"}
    assert all(name not in os.environ for name in NAMES)


def test_a_bad_credentials_file_stops_an_account_command_with_a_plain_error(capsys):
    write_saved(["POLYMARKET_API_KEY=x"], mode=0o666)
    with pytest.raises(SystemExit) as stopped:
        trading_cli.main(["status", "00000000-0000-0000-0000-000000000000"])
    assert stopped.value.code == 2 and "chmod 600" in capsys.readouterr().err


# --- trade setup ---

def run_setup(monkeypatch, capsys, save_answer):
    typing(monkeypatch, [SIGNER, save_answer])
    monkeypatch.setattr(trading_cli, "getpass", lambda prompt: "TOPSECRET-" + prompt.split("_", 1)[1][:6])
    trading_cli.main(["setup"])
    return capsys.readouterr()


def test_setup_saves_what_was_typed_only_after_a_typed_yes_and_never_prints_it(monkeypatch, capsys):
    shown = run_setup(monkeypatch, capsys, "yes")
    assert "TOPSECRET" not in shown.out + shown.err and "not responsible" in shown.err
    saved = account_setup.read_saved()
    assert saved["POLYMARKET_WALLET_ADDRESS"] == SIGNER and saved["POLYMARKET_API_KEY"].startswith("TOPSECRET-")
    assert set(saved) == set(NAMES) and account_setup.credentials_file().stat().st_mode & 0o077 == 0
    assert all(name not in os.environ for name in NAMES)


def test_setup_without_a_yes_saves_nothing(monkeypatch, capsys):
    shown = run_setup(monkeypatch, capsys, "no")
    assert "Not saved" in shown.err and not account_setup.credentials_file().exists()


def test_setup_refuses_a_script(monkeypatch, capsys):
    monkeypatch.setattr(trading_cli.sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        trading_cli.main(["setup"])
    assert "interactive terminal" in capsys.readouterr().err and not account_setup.credentials_file().exists()


# --- trade check ---

def set_account(monkeypatch, **changes):
    values = {"POLYMARKET_WALLET_ADDRESS": SIGNER, "POLYMARKET_SIGNER_PRIVATE_KEY": KEY, "POLYMARKET_API_KEY": "k",
              "POLYMARKET_API_SECRET": "s", "POLYMARKET_API_PASSPHRASE": "p", **changes}
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_check_names_what_is_missing_and_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as stopped:
        trading_cli.main(["check", "--offline"])
    report = json.loads(capsys.readouterr().out)
    assert stopped.value.code == 1 and report["ready"] is False
    assert len(report["problems"]) == 5 and report["items"]["POLYMARKET_API_KEY"] == "MISSING"


def test_check_offline_passes_with_a_valid_account_and_says_which_wallet_kind(monkeypatch, capsys):
    set_account(monkeypatch)
    trading_cli.main(["check", "--offline"])
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is True and report["items"]["wallet"] == "the signer's own address"
    assert report["items"]["live_flag"].startswith("not set") and KEY not in json.dumps(report)
    set_account(monkeypatch, POLYMARKET_WALLET_ADDRESS="0x" + "a" * 40)
    assert asyncio.run(account_setup.check(offline=True))["items"]["wallet"] == "a smart wallet that the signer controls"


@pytest.mark.parametrize("changes,words", [({"POLYMARKET_WALLET_ADDRESS": "0x123"}, "40 hexadecimal"),
                                           ({"POLYMARKET_SIGNER_PRIVATE_KEY": "not-a-key"}, "not a valid private key")])
def test_check_rejects_a_malformed_wallet_or_key_without_echoing_it(monkeypatch, changes, words):
    set_account(monkeypatch, **changes)
    report = asyncio.run(account_setup.check(offline=True))
    assert report["ready"] is False and words in " ".join(report["problems"])
    assert not any(value in json.dumps(report) for value in changes.values())


def test_check_stops_when_a_kill_file_exists(monkeypatch):
    set_account(monkeypatch)
    (safety.state_dir() / "KILL").touch()
    assert "kill switch engaged" in " ".join(asyncio.run(account_setup.check(offline=True))["problems"])


def test_check_online_reads_the_location_and_the_balance(monkeypatch):
    set_account(monkeypatch)
    state = {"blocked": False, "balance": "12.5", "allowance": "12.5"}
    monkeypatch.setattr(safety, "geoblock_status", lambda: {"blocked": state["blocked"]})

    async def balance():
        return {"pusd_balance": state["balance"], "pusd_allowance_by_exchange": {"0x" + "e" * 40: state["allowance"]}}
    monkeypatch.setattr(execution, "pusd_balance", balance)
    report = asyncio.run(account_setup.check())
    assert report["ready"] is True and report["items"]["location"] == "allowed" and report["items"]["account"]["pusd_balance"] == "12.5"
    state["balance"] = "0"
    assert "holds no pUSD" in " ".join(asyncio.run(account_setup.check())["problems"])
    state.update(balance="5", allowance="0")
    assert "allowed to spend" in " ".join(asyncio.run(account_setup.check())["problems"])
    state["blocked"] = True
    assert "geoblock" in " ".join(asyncio.run(account_setup.check())["problems"])


def test_check_says_so_when_the_location_check_cannot_reach_polymarket(monkeypatch):
    set_account(monkeypatch)
    monkeypatch.setattr(safety, "geoblock_status", lambda: (_ for _ in ()).throw(OSError("offline")))
    assert "could not reach" in " ".join(asyncio.run(account_setup.check())["problems"])


def test_pusd_balance_reads_the_collateral_balance_and_each_allowance(monkeypatch):
    class Client:
        wallet = SIGNER

        async def get_balance_allowance(self, **kwargs):
            assert kwargs == {"asset_type": "COLLATERAL"}
            return NS(balance=12_500_000, allowances={"0xExchange": 3_000_000})

    monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", SIGNER)
    assert asyncio.run(execution.pusd_balance(Client())) == {"pusd_balance": "12.5", "pusd_allowance_by_exchange": {"0xExchange": "3"}}


# --- trade approve and inspect's flags ---

def fixture():
    contract = {"slug": "synthetic-contract", "condition_id": "condition", "question": "Synthetic question?",
                "description": "Synthetic full rules", "resolution_source": "https://sources.test/rules",
                "end_time": NOW + 86400 * 30, "tokens": {"YES": "123", "NO": "456"}, "labels": {"YES": "Yes", "NO": "No"},
                "neg_risk": False, "version": "v1"}
    state = {"active": True, "closed": False, "archived": False, "accepting_orders": True, "enable_order_book": True, "uma_status": None}
    inspected = {"contract": contract, "state": state, "fingerprint": trade_plan.digest(contract),
                 "market": NS(trading=NS(fees_enabled=True, fee_schedule=NS(rate=0.04, exponent=1, rebate_rate=0, taker_only=True)))}
    book = NS(asset_id="123", condition_id="condition", neg_risk=False, timestamp=datetime.fromtimestamp(NOW, timezone.utc),
              asks=[NS(price=Decimal("0.50"), size=Decimal("10"))], bids=[NS(price=Decimal("0.48"), size=Decimal("10"))],
              tick_size=Decimal("0.01"), min_order_size=Decimal("5"))
    return inspected, book


def drafted(tmp_path, monkeypatch, **fields):
    inspected, book = fixture()

    async def inspect(slug, client=None):
        return inspected
    monkeypatch.setattr(trade_plan, "inspect", inspect)
    monkeypatch.setattr(trading_cli.time, "time", lambda: NOW + 5)
    path = tmp_path / "trade.json"
    config = trade_plan.draft_config(inspected, now=NOW, shares="5", limit_price="0.50", max_cash="10", **fields)
    path.write_text(json.dumps(config))
    return path, inspected, book


def test_approve_turns_a_draft_into_a_config_that_previews_as_eligible(tmp_path, monkeypatch):
    path, inspected, book = drafted(tmp_path, monkeypatch)
    before = json.loads(path.read_text())
    assert not trade_plan.build_preview(before, inspected, book, now=NOW + 6)["eligible"]
    typing(monkeypatch, ["Rain falls on the day", "Matches my weather view", "APPROVE"])
    trading_cli.main(["approve", str(path)])
    config = json.loads(path.read_text())
    assert config["approval"]["approved"] is True and config["approval"]["yes_definition"] == "Rain falls on the day"
    assert config["approval"]["fingerprint"] == inspected["fingerprint"] and config["approval"]["valid_until"] == NOW + 5 + 3600
    assert config["intent_id"] == before["intent_id"] and not Path(f"{path}.tmp").exists()
    assert trade_plan.build_preview(config, inspected, book, now=NOW + 6)["eligible"] is True


def test_approve_changes_nothing_without_a_typed_approve_or_a_full_answer(tmp_path, monkeypatch, capsys):
    path, _, _ = drafted(tmp_path, monkeypatch)
    original = path.read_text()
    for answers in (["Rain", "Because", "approve"], ["Rain", "Because", ""], ["", "Because", "APPROVE"], ["Rain", "", "APPROVE"]):
        typing(monkeypatch, answers)
        with pytest.raises(SystemExit):
            trading_cli.main(["approve", str(path)])
        assert path.read_text() == original
    capsys.readouterr()


def test_approve_is_only_for_your_own_terminal(tmp_path, monkeypatch, capsys):
    path, _, _ = drafted(tmp_path, monkeypatch)
    original = path.read_text()
    monkeypatch.setattr(trading_cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("a script must not be asked"))
    with pytest.raises(SystemExit):
        trading_cli.main(["approve", str(path)])
    assert "interactive terminal" in capsys.readouterr().err and path.read_text() == original


def test_approve_keeps_the_strategys_own_definition_on_enter_and_refreshes_a_stale_expiry(tmp_path, monkeypatch):
    path, _, _ = drafted(tmp_path, monkeypatch)
    config = json.loads(path.read_text())
    config["strategy"] = {"kind": "model_value", "min_edge": 0.02, "inputs": {"target_yes_definition": "Exactly this event"}}
    config["expires_at"] = NOW + 10
    path.write_text(json.dumps(config))
    typing(monkeypatch, ["", "Matches my forecast", "APPROVE"])
    trading_cli.main(["approve", str(path), "--minutes", "30"])
    approved = json.loads(path.read_text())
    assert approved["approval"]["yes_definition"] == "Exactly this event" and approved["approval"]["valid_until"] == NOW + 5 + 1800
    assert approved["expires_at"] == NOW + 5 + 660


def test_approve_asks_for_the_source_only_when_the_market_names_none(tmp_path, monkeypatch):
    path, inspected, _ = drafted(tmp_path, monkeypatch)
    inspected["contract"]["resolution_source"] = ""
    inspected["fingerprint"] = trade_plan.digest(inspected["contract"])
    typing(monkeypatch, ["Rain", "https://sources.test/weather", "Because", "APPROVE"])
    trading_cli.main(["approve", str(path)])
    assert json.loads(path.read_text())["approval"]["resolution_source"] == "https://sources.test/weather"


@pytest.mark.parametrize("minutes", ["9", "1441"])
def test_approve_keeps_the_approval_window_between_ten_minutes_and_a_day(tmp_path, monkeypatch, minutes, capsys):
    path, _, _ = drafted(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as stopped:
        trading_cli.main(["approve", str(path), "--minutes", minutes])
    assert stopped.value.code == 2 and "between 10 and 1440" in capsys.readouterr().err


def test_inspect_flags_fill_the_order_and_its_limits(tmp_path, monkeypatch):
    inspected, _ = fixture()

    async def inspect(slug, client=None):
        return inspected
    monkeypatch.setattr(trade_plan, "inspect", inspect)
    out = tmp_path / "trade.json"
    trading_cli.main(["inspect", "synthetic-contract", "--outcome", "NO", "--shares", "8", "--price", "0.35", "--max-cash", "4", "--out", str(out)])
    config = json.loads(out.read_text())
    assert (config["outcome"], config["side"], config["shares"], config["limit_price"]) == ("NO", "BUY", "8", "0.35")
    assert config["limits"]["max_cash"] == "4" and config["limits"]["max_shares"] == "8" and config["approval"]["approved"] is False


def test_inspect_without_flags_still_leaves_every_limit_at_zero():
    inspected, _ = fixture()
    config = trade_plan.draft_config(inspected, now=NOW)
    assert config["limits"]["max_cash"] == "0" and config["limits"]["max_shares"] == "0" and config["shares"] == "5"


@pytest.mark.parametrize("flag,value", [("--shares", "0"), ("--shares", "abc"), ("--price", "-1"), ("--max-cash", "NaN")])
def test_inspect_rejects_a_bad_number_before_any_request(tmp_path, monkeypatch, flag, value, capsys):
    async def inspect(slug, client=None):
        pytest.fail("no request for a bad number")
    monkeypatch.setattr(trade_plan, "inspect", inspect)
    with pytest.raises(SystemExit):
        trading_cli.main(["inspect", "synthetic-contract", flag, value])
    assert capsys.readouterr().err


# --- the risk notice ---

def test_submit_shows_the_risk_notice_before_asking(monkeypatch, capsys):
    async def submit(*args, **kwargs):
        return {"ok": True, "phase": "ACCEPTED"}
    monkeypatch.setattr(execution, "submit", submit)
    path = Path(os.environ["POLYMARKET_STRATEGIES_HOME"]) / "plan.json"
    path.write_text('{"intent_id": "synthetic"}')
    trading_cli.main(["submit", str(path), "--confirm", "x", "--live", "--yes"])
    assert safety.DISCLAIMER in capsys.readouterr().err


def test_the_readme_and_the_trading_guide_carry_the_risk_notice():
    root = Path(__file__).resolve().parent.parent
    for name in ("README.md", "TRADING.md"):
        assert "not responsible for any investment loss" in (root / name).read_text(), name


def test_approve_never_outlasts_the_forecast_and_refuses_when_too_little_time_is_left(tmp_path, monkeypatch, capsys):
    path, _, _ = drafted(tmp_path, monkeypatch)
    config = json.loads(path.read_text())
    config["strategy"] = {"kind": "model_value", "min_edge": 0.02, "inputs": {"target_yes_definition": "Exactly this event", "valid_until": NOW + 905}}
    path.write_text(json.dumps(config))
    typing(monkeypatch, ["", "Because", "APPROVE"])
    trading_cli.main(["approve", str(path)])
    assert json.loads(path.read_text())["approval"]["valid_until"] == NOW + 905
    config["strategy"]["inputs"]["valid_until"] = NOW + 200
    path.write_text(json.dumps(config))
    original = path.read_text()
    typing(monkeypatch, ["", "Because", "APPROVE"])  # every answer is given, so only the time check can stop it
    with pytest.raises(SystemExit):
        trading_cli.main(["approve", str(path)])
    assert path.read_text() == original and "too soon for an order" in capsys.readouterr().err


def test_approval_and_order_expiry_start_when_you_approve_not_when_you_started_reading(tmp_path, monkeypatch):
    path, inspected, book = drafted(tmp_path, monkeypatch)
    clock = iter([NOW + 5, NOW + 500])  # the first look at the clock, then the moment of approval, eight minutes later
    monkeypatch.setattr(trading_cli.time, "time", lambda: next(clock))
    typing(monkeypatch, ["Rain", "Because", "APPROVE"])
    trading_cli.main(["approve", str(path)])
    config = json.loads(path.read_text())
    assert config["approval"]["reviewed_at"] == NOW + 500 and config["approval"]["valid_until"] == NOW + 500 + 3600
    assert config["expires_at"] == NOW + 500 + 660  # the drafted expiry (NOW + 660) would have been too close to submit
    book.timestamp = datetime.fromtimestamp(NOW + 501, timezone.utc)
    assert trade_plan.build_preview(config, inspected, book, now=NOW + 501)["eligible"] is True


def test_the_shortest_approval_still_leaves_an_order_that_expires_before_it_does(tmp_path, monkeypatch):
    path, inspected, book = drafted(tmp_path, monkeypatch)
    typing(monkeypatch, ["Rain", "Because", "APPROVE"])
    trading_cli.main(["approve", str(path), "--minutes", "10"])
    config = json.loads(path.read_text())
    assert config["approval"]["valid_until"] == NOW + 5 + 600 and config["expires_at"] == NOW + 5 + 600  # was NOW + 660, after the approval ended
    assert trade_plan.build_preview(config, inspected, book, now=NOW + 6)["eligible"] is True
