"""Keep every test away from the real per-user ledger and KILL folder."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_state_folder(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("POLYMARKET_STRATEGIES_HOME", str(tmp_path_factory.mktemp("state")))
