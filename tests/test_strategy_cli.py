"""Reader-facing indexed commands and local plan preparation never touch an account."""
import json

import pytest

from polymarket_strategies import strategy_catalog as catalog, strategy_cli
from polymarket_strategies.__main__ import main
from helpers import as_if_real
from test_trade_plan import NOW, fixture


def test_main_lists_all_35_without_a_market_or_account(capsys):
    main(["strategy", "list"])
    rows = json.loads(capsys.readouterr().out)["strategies"]
    assert len(rows) == 35 and rows[6]["id"] == "C8" and rows[-1]["id"] == "H2"


@pytest.mark.parametrize("index", ["10", "C1", "07"])
def test_cli_examples_accept_both_numbers_and_card_ids(index, capsys):
    strategy_cli.main(["example", index])
    assert json.loads(capsys.readouterr().out)["demo"] is True


def test_analysis_reports_rejection_without_attempting_an_order(tmp_path, capsys):
    inputs = catalog.example(10, now=NOW)
    inputs["probability_yes"] = -1
    path = tmp_path / "forecast-local.json"
    path.write_text(json.dumps(inputs))
    strategy_cli.main(["analyze", "10", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert result["eligible"] is False and result["order_authorized"] is False and result["reasons"]


def test_prepare_saves_only_a_new_unapproved_plan_and_never_overwrites(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(strategy_cli.time, "time", lambda: NOW)
    inputs = as_if_real(catalog.example(10, now=NOW))
    inputs.pop("demo")
    config, _, _ = fixture()
    path, inspected, out = (tmp_path / name for name in ("forecast-local.json", "inspected-local.json", "trade-local.json"))
    path.write_text(json.dumps(inputs))
    inspected.write_text(json.dumps(config))
    args = ["prepare", "C1", str(path), str(inspected), "--out", str(out)]
    strategy_cli.main(args)
    saved = json.loads(out.read_text())
    assert saved["strategy"]["inputs"]["strategy_index"] == 10
    assert saved["approval"]["approved"] is False and saved["intent_id"] != config["intent_id"]
    before = out.read_bytes()
    with pytest.raises(SystemExit) as error:
        strategy_cli.main(args)
    assert error.value.code == 2 and out.read_bytes() == before


def test_nested_secret_and_nonfinite_json_diagnostics_do_not_print_values(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"unused": {"api_key": "SECRET_VALUE_MUST_NOT_APPEAR"}}')
    with pytest.raises(SystemExit):
        strategy_cli.main(["analyze", "10", str(path)])
    output = capsys.readouterr()
    assert "SECRET_VALUE" not in output.out + output.err
    path.write_text('{"unused": 1e999}')
    with pytest.raises(SystemExit):
        strategy_cli.main(["analyze", "10", str(path)])
    assert "finite" in capsys.readouterr().err


def test_entry_example_cannot_be_combined_with_plan_options(capsys):
    with pytest.raises(SystemExit) as error:
        strategy_cli.entry_main(10, ["--example", "--inputs", "ignored.json"])
    assert error.value.code == 2


def test_entry_does_not_silently_ignore_a_plan_only_edge_flag():
    with pytest.raises(SystemExit) as error:
        strategy_cli.entry_main(10, ["--min-edge", "0.1"])
    assert error.value.code == 2


def real_inputs(**changes):
    inputs = as_if_real(catalog.example(10, now=NOW))
    inputs.pop("demo")
    inputs.update(changes)
    return inputs


@pytest.mark.parametrize("flag,written,expected", [(None, None, 0.02), (0.05, None, 0.05), (None, 0.1, 0.1),
                                                   (0.05, 0.1, 0.1), (0.2, 0.1, 0.2), (0, 0, 0.0)])
def test_the_stricter_of_the_flag_and_the_inputs_minimum_edge_is_saved(flag, written, expected):
    config, _, _ = fixture()
    inputs = real_inputs()
    inputs.pop("min_edge", None)
    if written is not None:
        inputs["min_edge"] = written
    assert strategy_cli.prepare(10, inputs, config, min_edge=flag, now=NOW)["strategy"]["min_edge"] == expected


@pytest.mark.parametrize("bad", [-0.01, float("inf"), True])
def test_an_unusable_minimum_edge_is_refused_before_a_plan_is_saved(bad):
    config, _, _ = fixture()
    with pytest.raises(ValueError, match="min_edge"):
        strategy_cli.prepare(10, real_inputs(), config, min_edge=bad, now=NOW)


def test_placeholder_text_is_refused_even_when_the_demo_flag_was_deleted():
    config, _, _ = fixture()
    raw = catalog.example(10, now=NOW)
    raw.pop("demo")
    with pytest.raises(ValueError, match="placeholder"):
        strategy_cli.prepare(10, raw, config, now=NOW)


def test_analyze_does_not_call_leftover_placeholder_text_eligible_once_the_demo_flag_is_deleted(tmp_path, capsys):
    """Report M's case: an example with only `demo: true` removed printed eligible true and synthetic false."""
    path = tmp_path / "inputs-local.json"
    strategy_cli.main(["example", "10", "--out", str(path)])
    capsys.readouterr()
    strategy_cli.main(["analyze", "10", str(path)])
    demo = json.loads(capsys.readouterr().out)
    assert demo["eligible"] is True and demo["synthetic"] is True  # the marked demonstration itself is unchanged
    inputs = json.loads(path.read_text())
    inputs.pop("demo")
    path.write_text(json.dumps(inputs))
    strategy_cli.main(["analyze", "10", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert result["eligible"] is False and result["synthetic"] is True and result["order_authorized"] is False
    assert result["reasons"][0] == catalog.PLACEHOLDER_MESSAGE
    path.write_text(json.dumps(as_if_real(inputs)))
    strategy_cli.main(["analyze", "10", str(path)])
    replaced = json.loads(capsys.readouterr().out)
    assert replaced["eligible"] is True and replaced["synthetic"] is False


@pytest.mark.parametrize("index", (26, 1, 22))
def test_analyze_flags_placeholder_text_for_every_kind_of_tool(index):
    """Analysis-only tools too, including Strategy 26, whose no-screen result would otherwise read eligible null."""
    raw = catalog.example(index, now=NOW)
    raw.pop("demo")
    result = catalog.analyze(index, raw, now=NOW)
    assert result["eligible"] is False and result["synthetic"] is True
    assert result["reasons"][0] == catalog.PLACEHOLDER_MESSAGE


def test_an_old_inspect_file_gets_a_fresh_order_window_and_a_short_forecast_explains_itself():
    config, _, _ = fixture()
    config["expires_at"] = NOW - 5000  # `trade inspect` wrote this file long ago
    prepared = strategy_cli.prepare(10, real_inputs(valid_until=NOW + 86400), config, now=NOW)
    assert NOW + 185 <= prepared["expires_at"] <= NOW + 3600
    with pytest.raises(ValueError, match="three minutes.*trade inspect"):
        strategy_cli.prepare(10, real_inputs(valid_until=NOW + 100), config, now=NOW)


def test_prepare_runs_the_strategys_own_screen_and_refuses_inputs_that_fail_it():
    config, _, _ = fixture()
    weak = real_inputs(probability_yes=0.36, conservative_low_yes=0.30, conservative_high_yes=0.40)  # no edge over a 0.35 limit plus the fee
    with pytest.raises(ValueError, match="own screen.*edge"):
        strategy_cli.prepare(10, weak, config, now=NOW)


def test_prepare_carries_the_inputs_outcome_into_the_plan():
    config, _, _ = fixture()
    assert config["outcome"] == "YES"
    inputs = real_inputs(outcome="NO", probability_yes=0.25, conservative_low_yes=0.15, conservative_high_yes=0.35, limit_price=0.55)
    assert strategy_cli.prepare(10, inputs, config, now=NOW)["outcome"] == "NO"
    assert strategy_cli.prepare(10, real_inputs(), config, now=NOW)["outcome"] == "YES"


def test_a_launcher_describes_its_scope_in_words_not_internal_mode_names(capsys):
    with pytest.raises(SystemExit):
        strategy_cli.entry_main(10, ["--help"])
    text = capsys.readouterr().out
    assert "can feed a reviewed order plan" in text and "forecast_order" not in text
    with pytest.raises(SystemExit):
        strategy_cli.entry_main(1, ["--help"])
    assert "analysis only" in capsys.readouterr().out


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
def test_input_files_saved_by_windows_editors_and_shells_are_read(tmp_path, capsys, encoding):
    """PowerShell 5's `>` writes UTF-16 and Notepad may add a byte-order mark; both used to fail with a decode error."""
    inputs = catalog.example(10, now=NOW)
    path = tmp_path / "forecast-local.json"
    path.write_text(json.dumps(inputs), encoding=encoding)
    strategy_cli.main(["analyze", "10", str(path)])
    assert json.loads(capsys.readouterr().out)["strategy"]["index"] == 10
    from polymarket_strategies.trading_cli import load_config
    path.write_text(json.dumps({"shares": "5"}), encoding=encoding)
    assert load_config(str(path)) == {"shares": "5"}


def test_example_out_writes_a_new_utf8_file_and_never_overwrites(tmp_path, capsys):
    out = tmp_path / "inputs-local.json"
    strategy_cli.main(["example", "10", "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["demo"] is True and "wrote" in capsys.readouterr().err
    before = out.read_bytes()
    with pytest.raises(SystemExit) as error:
        strategy_cli.main(["example", "10", "--out", str(out)])
    assert error.value.code == 2 and out.read_bytes() == before
    assert "already exists; choose a new name" in capsys.readouterr().err  # a plain sentence, not the raw errno text
