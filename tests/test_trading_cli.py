"""CLI failures and secret prompting, using only injected local values."""
import json
import os

import pytest

from polymarket_strategies import execution, trading_cli


def test_failed_submission_prints_sanitized_result_and_exits_nonzero(monkeypatch, tmp_path, capsys):
    config = tmp_path / "plan.json"
    config.write_text('{"intent_id": "synthetic"}')
    async def submit(*args, **kwargs):
        return {"ok": False, "phase": "UNKNOWN", "error": "Do not retry"}
    monkeypatch.setattr(execution, "submit", submit)
    with pytest.raises(SystemExit) as error:
        trading_cli.main(["submit", str(config), "--confirm", "synthetic", "--live", "--yes"])
    assert error.value.code == 1
    assert json.loads(capsys.readouterr().out)["phase"] == "UNKNOWN"


def preview_for_confirmation(monkeypatch, plan_id="abc123"):
    async def preview(config):
        return {"eligible": True, "plan_id": plan_id, "cash_bound": "2.6",
                "order": {"price": "0.5", "size": "5", "side": "BUY", "expiration": 2_000_000_000},
                "contract": {"question": "Will it happen?", "labels": {"YES": "Yes", "NO": "No"}}}
    monkeypatch.setattr(trading_cli.trade_plan, "preview", preview)


def test_submit_needs_a_typed_yes_unless_yes_flag_is_given(monkeypatch, tmp_path, capsys):
    config = tmp_path / "plan.json"
    config.write_text('{"intent_id": "synthetic", "outcome": "YES"}')
    sent = []

    async def submit(*args, **kwargs):
        sent.append(1)
        return {"ok": True, "phase": "ACCEPTED"}
    monkeypatch.setattr(execution, "submit", submit)
    preview_for_confirmation(monkeypatch)
    args = ["submit", str(config), "--confirm", "abc123", "--live"]
    monkeypatch.setattr(trading_cli.sys.stdin, "isatty", lambda: False)  # a script cannot answer the question
    with pytest.raises(SystemExit):
        trading_cli.main(args)
    assert not sent and "typed confirmation" in capsys.readouterr().err
    monkeypatch.setattr(trading_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes please")
    with pytest.raises(SystemExit):
        trading_cli.main(args)
    assert not sent and "Not confirmed" in capsys.readouterr().err
    monkeypatch.setattr("builtins.input", lambda prompt: "YES")
    trading_cli.main(args)
    assert sent == [1]
    err = capsys.readouterr().err
    assert "Will it happen?" in err and "Yes" in err and "ledger:" in err


def test_default_ledger_is_the_same_file_from_any_folder(monkeypatch, tmp_path):
    home = tmp_path / "state"
    monkeypatch.setenv("POLYMARKET_STRATEGIES_HOME", str(home))
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        monkeypatch.chdir(tmp_path / folder)
        assert trading_cli.default_ledger() == str(home / "orders.sqlite3")


def test_a_relative_state_folder_stops_every_account_command_with_a_plain_error(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POLYMARKET_STRATEGIES_HOME", "state")
    with pytest.raises(ValueError, match="absolute"):
        trading_cli.default_ledger()
    with pytest.raises(SystemExit) as stopped:
        trading_cli.main(["ledger"])
    assert stopped.value.code == 2 and "POLYMARKET_STRATEGIES_HOME must be an absolute path" in capsys.readouterr().err
    assert not (tmp_path / "state").exists()


def test_prompted_credentials_exist_only_during_command(monkeypatch):
    for name in trading_cli.CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(trading_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "local-public-wallet")
    monkeypatch.setattr(trading_cli, "getpass", lambda prompt: "local-hidden-test-value")
    async def run(args):
        assert os.environ["POLYMARKET_WALLET_ADDRESS"] == "local-public-wallet"
        assert all(os.environ[n] == "local-hidden-test-value" for n in trading_cli.CREDENTIAL_NAMES[1:])
    monkeypatch.setattr(trading_cli, "run", run)
    trading_cli.main(["status", "synthetic", "--prompt-credentials"])
    assert all(n not in os.environ for n in trading_cli.CREDENTIAL_NAMES)


def test_noninteractive_prompt_rejects_before_reading_secrets(monkeypatch):
    monkeypatch.setattr(trading_cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(trading_cli, "getpass", lambda prompt: pytest.fail("Secret prompt should not run"))
    with pytest.raises(ValueError, match="interactive terminal"):
        trading_cli.prompt_credentials()


def test_existing_environment_is_restored_after_error(monkeypatch):
    for name in trading_cli.CREDENTIAL_NAMES:
        monkeypatch.setenv(name, "existing-local-test-value")
    async def run(args):
        os.environ["POLYMARKET_API_KEY"] = "temporary-local-test-value"
        raise RuntimeError("SDK_PRIVATE_ERROR_MUST_NOT_PRINT")
    monkeypatch.setattr(trading_cli, "run", run)
    with pytest.raises(SystemExit):
        trading_cli.main(["status", "synthetic"])
    assert all(os.environ[n] == "existing-local-test-value" for n in trading_cli.CREDENTIAL_NAMES)


def test_known_safe_operational_error_is_actionable(monkeypatch, capsys):
    async def run(args):
        raise execution.ExecutionError("Insufficient balance or allowance for the selected exchange")
    monkeypatch.setattr(trading_cli, "run", run)
    with pytest.raises(SystemExit) as failure:
        trading_cli.main(["status", "synthetic"])
    assert failure.value.code == 1
    assert "Insufficient balance or allowance" in capsys.readouterr().err


def test_a_status_watch_keeps_polling_after_a_failed_check_and_ends_nonzero(monkeypatch, capsys):
    answers = iter([{"ok": False, "phase": "UNKNOWN", "trades_complete": False, "error": "could not verify"},
                    {"ok": True, "phase": "ACCEPTED", "trades_complete": True}])
    polled = []

    async def status(intent_id, ledger):
        polled.append(intent_id)
        return next(answers)

    async def no_sleep(seconds):
        return None
    monkeypatch.setattr(execution, "status", status)
    monkeypatch.setattr(trading_cli.asyncio, "sleep", no_sleep)
    with pytest.raises(SystemExit) as failure:
        trading_cli.main(["status", "11111111-1111-1111-1111-111111111111", "--count", "2"])
    assert failure.value.code == 1 and len(polled) == 2  # the transient failure did not end the watch
    assert capsys.readouterr().out.count('"phase"') == 2


def test_a_status_watch_stops_at_once_when_no_order_exists(monkeypatch, capsys):
    polled = []

    async def status(intent_id, ledger):
        polled.append(1)
        return {"ok": False, "phase": "REJECTED", "error": "Polymarket refused this order, so no order exists."}
    monkeypatch.setattr(execution, "status", status)
    with pytest.raises(SystemExit) as failure:
        trading_cli.main(["status", "11111111-1111-1111-1111-111111111111", "--count", "5"])
    assert failure.value.code == 1 and polled == [1]


def test_a_sell_prompt_does_not_claim_zero_pusd_at_risk_and_the_live_flag_is_checked_before_the_prompt(monkeypatch, tmp_path, capsys):
    config = tmp_path / "plan.json"
    config.write_text('{"intent_id": "synthetic", "outcome": "YES"}')

    async def preview(config):
        return {"eligible": True, "plan_id": "abc123", "cash_bound": "0",
                "order": {"price": "0.48", "size": "5", "side": "SELL", "expiration": 2_000_000_000},
                "contract": {"question": "Will it happen?", "labels": {"YES": "Yes", "NO": "No"}}}
    monkeypatch.setattr(trading_cli.trade_plan, "preview", preview)
    monkeypatch.setattr(trading_cli.sys.stdin, "isatty", lambda: True)
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "no")
    with pytest.raises(SystemExit):
        trading_cli.main(["submit", str(config), "--confirm", "abc123"])  # no --live
    assert not asked and "pass --live" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        trading_cli.main(["submit", str(config), "--confirm", "abc123", "--live"])
    err = capsys.readouterr().err
    assert asked and "Sells 5 shares" in err and "0 pUSD at risk" not in err


def test_the_typed_confirmation_refuses_a_wrong_plan_id_an_ineligible_preview_and_anything_but_yes(monkeypatch, capsys):
    import asyncio
    state = {"eligible": True, "plan_id": "abc123"}

    async def preview(config):
        return {**state, "cash_bound": "2.55001", "order": {"price": "0.50", "size": "5", "side": "BUY", "expiration": 2_000_000_000},
                "contract": {"question": "Will it happen?", "labels": {"YES": "Yes", "NO": "No"}}}
    monkeypatch.setattr(trading_cli.trade_plan, "preview", preview)
    monkeypatch.setattr(trading_cli.sys.stdin, "isatty", lambda: True)
    asked = []
    answers = iter(["yes", "", "YES"])  # only the exact word YES places an order
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or next(answers))
    config = {"outcome": "YES"}
    with pytest.raises(trading_cli.ExecutionError, match="exact plan ID"):
        asyncio.run(trading_cli.confirm_in_terminal(config, "other-id"))
    state["eligible"] = False
    with pytest.raises(trading_cli.ExecutionError, match="exact plan ID"):
        asyncio.run(trading_cli.confirm_in_terminal(config, "abc123"))
    assert not asked  # nothing was shown or asked for a preview that does not match or is not eligible
    state["eligible"] = True
    for _ in range(2):
        with pytest.raises(trading_cli.ExecutionError, match="Not confirmed"):
            asyncio.run(trading_cli.confirm_in_terminal(config, "abc123"))
    asyncio.run(trading_cli.confirm_in_terminal(config, "abc123"))
    assert len(asked) == 3 and "At most 2.55001 pUSD at risk" in capsys.readouterr().err


def test_a_read_only_lookup_that_cannot_reach_polymarket_says_so_without_mentioning_a_ledger(monkeypatch, capsys):
    import httpx

    async def refuse(self, request, **kwargs):
        raise httpx.ConnectError("403 Forbidden", request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)  # offline: the SDK's transport fails as an unreachable network does
    with pytest.raises(SystemExit) as failure:
        trading_cli.main(["inspect", "some-market-slug"])
    assert failure.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("trade inspect: could not read Polymarket's public data (403 Forbidden)") and err.count("\n") == 1
    assert "ledger" not in err.lower() and "placed no order" in err


def test_any_other_failure_of_a_read_only_lookup_names_no_ledger_and_no_details(monkeypatch, capsys):
    async def run(args):
        raise RuntimeError("SDK_DETAIL_MUST_NOT_PRINT")
    monkeypatch.setattr(trading_cli, "run", run)
    with pytest.raises(SystemExit) as failure:
        trading_cli.main(["inspect", "some-market-slug"])
    assert failure.value.code == 1
    err = capsys.readouterr().err
    assert "read-only lookup failed (RuntimeError)" in err and "ledger" not in err.lower() and "SDK_DETAIL" not in err
    with pytest.raises(SystemExit):
        trading_cli.main(["status", "synthetic"])  # an account command keeps the ledger advice
    assert "Check the local ledger" in capsys.readouterr().err
