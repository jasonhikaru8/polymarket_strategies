"""Run the public exercises from this package, excluding live-data calls."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((ROOT / "chapters").glob("ch*/*.py"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: str(path.relative_to(ROOT)))
def test_chapter_exercise_runs(script):
    args = [sys.executable, str(script)]
    if script.parent.name == "ch14":
        args.append("--help")  # the resolution reader requires a live endpoint and user-supplied slug
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


@pytest.mark.parametrize("args", [
    ["--price", "0"], ["--price", "1"], ["--price", "0.5", "--shares", "-1"],
    ["--price", "0.5", "--days", "0"], ["--price", "0.5", "--prob", "1.1"],
    ["--price", "0.5", "--rate", "-0.01"], ["--price", "0.999", "--rate", "5"],  # the fee pushes the cost to $1 or more
    ["--price", "nan"], ["--price", "0.5", "--shares", "inf"], ["--price", "0.5", "--days", "nan"],
    ["--price", "0.5", "--rate", "nan"], ["--price", "0.5", "--prob", "nan"],
])
def test_calculator_rejects_invalid_inputs(args):
    from polymarket_strategies.__main__ import main

    with pytest.raises(SystemExit) as failure:
        main(["calc", *args])
    assert failure.value.code == 2



# What each exercise must print: the numbers the book prints next to it. A wrong number now fails here, not only a crash.
PRINTED = {
    "ch01/01_edge_after_costs.py": ["'gross_edge': 0.02,", "'edge_after_spread_and_fee': 0.002501,", "'break_even_probability': 0.517499}"],  # rounded: no float noise
    "ch02/01_complete_set.py": ["'taker_fee': 0.11655", "'cash_after_selling_yes': 93.58", "'cash_at_end_if_NO_wins': 103.58", "'cash_at_end_if_YES_wins': 93.58"],
    "ch03/01_fees_and_break_even.py": ["'fee_for_100_shares': 0.19", "'break_even_probability': 0.9519"],
    "ch04/01_fractional_kelly.py": ["'full_kelly': 0.13518", "'quarter_kelly_capped': 0.03379"],
    "ch05/02_paper_journal.py": ["'decisions': 12", "'independent_decisions': 6", "'win_rate': 0.5", "'mean_net_pnl_per_decision': 0.9833", "(-3.35, 4.53)"],
    "ch06/01_parity_at_depth.py": ["'sets': 150.0", "'profit': 4.272", "'profit_per_set': 0.02848", "'profit_per_set': 0.03518", "'profit_per_set': 0.01508"],
    "ch07/01_nested_contracts.py": ["'sets': 100.0", "'profit': 2.32319", "'profit_per_set': 0.02323"],
    "ch08/01_favorite_carry.py": ["'return_if_win': 0.0505", "'annualized_if_win': 0.4915", "'wins_canceled_by_one_loss': 19.79"],
    "ch10/01_crypto_probabilities.py": ["'terminal_above': 0.2307", "'touch_up_before_end': 0.4821", "'average_ends_at_or_above': 0.3545", "'disagree': 0.1169"],
    "ch11/01_reaction_and_fade.py": ["'move': {60: 0.2, 300: 0.1, 3600: 0.05}", "'implied_rumor_probability': 0.3333", "'fade_value_before_costs': 0.08}"],  # rounded: no float noise
    "ch12/01_base_rate_interval.py": ["'observed_frequency': 0.6", "0.31266", "0.83182"],
    "ch13/01_latency_budget.py": ["'seconds_before_possible_fill': 4.0", "'estimated_edge_after_entry_fee': 0.012}"],  # rounded: no float noise
    "ch16/01_wallet_audit.py": ["'distinct_events': 10", "'net_pnl': -70.0"],
    "ch18/01_martingale_exposure.py": ["'lost_after_six_losses': 630", "'next_bet': 640", "254.0"],
    "ch19/01_test_plan.py": ["'decisions_per_week_needed': 34", "'a': 20.0"],
}


@pytest.mark.parametrize("name", sorted(PRINTED))
def test_exercise_prints_the_numbers_the_chapter_prints(name):
    script = ROOT / "chapters" / name
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    for fragment in PRINTED[name]:
        assert fragment in result.stdout, f"{fragment!r} missing from {name} output: {result.stdout}"


def test_top_level_help_and_version_work_and_an_unknown_command_is_a_usage_error(capsys):
    from polymarket_strategies.__main__ import main

    main(["--help"])
    assert "commands:" in capsys.readouterr().out
    main(["--version"])
    assert capsys.readouterr().out.strip().count(".") == 2
    for argv in ([], ["bogus"]):
        with pytest.raises(SystemExit) as failure:
            main(argv)
        assert failure.value.code == 2
        assert "usage: polymarket-strategies" in capsys.readouterr().err
