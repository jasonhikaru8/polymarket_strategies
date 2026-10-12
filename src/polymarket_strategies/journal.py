"""Paper-decision journal: log decisions before the result is known, resolve them later, check the gates.

A decision is one bet you chose to make. Linked bets (five buckets of the same city and day) share one
`group` and count once. The 100 and 300 group counts are illustrative checkpoints, not universal
sample requirements. This summary supplies a numerical screen, not approval to trade.
"""
from __future__ import annotations

import json
import time
import uuid
from math import isfinite
from pathlib import Path

from .edge_check import bootstrap_mean

PAPER_GATE = 100
EVIDENCE_GATE = 300


def _validate_row(row: dict) -> None:
    if not isinstance(row, dict) or row.get("kind") not in ("decision", "outcome"):
        raise ValueError("journal row must be a decision or outcome")
    if not isinstance(row.get("id"), str) or not row["id"].strip():
        raise ValueError("journal row requires a nonempty decision id")
    if row["kind"] == "outcome":
        if type(row.get("won")) is not bool:
            raise ValueError("outcome must be a boolean")
        return
    for field in ("strategy", "market", "group"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ValueError(f"decision requires a nonempty {field}")
    for field in ("ask", "shares", "fee"):
        value = row.get(field)
        if type(value) not in (int, float) or not isfinite(value):
            raise ValueError(f"decision {field} must be finite")
    if not 0 < row["ask"] < 1 or row["shares"] <= 0 or row["fee"] < 0:
        raise ValueError("decision requires an ask in (0, 1), positive shares and a nonnegative total fee")
    probability = row.get("model_prob")
    if probability is not None and (type(probability) not in (int, float) or
                                    not isfinite(probability) or not 0 <= probability <= 1):
        raise ValueError("model probability must be finite and in [0, 1]")
    if row.get("role", "taker") not in ("maker", "taker"):
        raise ValueError("role must be maker or taker")


def _append(path: Path, row: dict) -> None:
    _validate_row(row)
    encoded = json.dumps(row, allow_nan=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(encoded + "\n")


def log_decision(path: str | Path, *, strategy: str, market: str, group: str, ask: float, shares: float,
                 fee: float = 0.0, model_prob: float | None = None, note: str = "", role: str = "taker") -> str:
    """Record a paper decision at the ask, with fee as the total USDC charge. Returns its id."""
    decision_id = uuid.uuid4().hex[:12]
    _append(Path(path), {"kind": "decision", "id": decision_id, "ts": time.time(), "strategy": strategy,
                         "market": market, "group": group, "ask": ask, "shares": shares, "fee": fee,
                         "model_prob": model_prob, "note": note, "role": role})
    return decision_id


def log_outcome(path: str | Path, decision_id: str, won: bool) -> None:
    """Record how a decision resolved. Entries are append-only: never edit old lines."""
    _append(Path(path), {"kind": "outcome", "id": decision_id, "ts": time.time(), "won": won})


def summarize(path: str | Path, seed: int = 0, strategy: str | None = None) -> dict:
    """Summarize fully resolved groups. An empirical bootstrap cannot infer an unseen loss tail.

    Keep one journal per test: decisions of different strategies in one file are pooled into one interval unless you pass `strategy`.
    Profit is in dollars per decision (all the linked bets of a group added up), so mixing position sizes mixes units.
    While any logged group is pending, the analyzed groups are the ones that resolved first, which can differ from
    the sample fixed in advance (a market can resolve early because of how it resolves), so the evidence screen stays off.
    """
    decisions: dict[str, dict] = {}
    outcomes: dict[str, bool] = {}
    duplicate_outcomes = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue  # a trailing or stray blank line is not a record
        row = json.loads(line)
        _validate_row(row)
        if row["kind"] == "decision":
            if row["id"] in decisions:
                raise ValueError("duplicate decision id cannot rewrite the paper record")
            decisions[row["id"]] = row
        elif row["id"] in outcomes:
            duplicate_outcomes += 1  # the first outcome stands: a later line cannot rewrite it. It is counted and reported.
        else:
            outcomes[row["id"]] = row["won"]
    orphan_outcomes = sum(1 for decision_id in outcomes if decision_id not in decisions)  # a typo'd id never settles anything
    strategies = sorted({d["strategy"] for d in decisions.values()})
    if strategy is not None:
        decisions = {key: d for key, d in decisions.items() if d["strategy"] == strategy}
    resolved = [d for d in decisions.values() if d["id"] in outcomes]
    pending_groups = {d["group"] for d in decisions.values() if d["id"] not in outcomes}
    analyzed = [d for d in resolved if d["group"] not in pending_groups]
    pnl = [d["shares"] * (1.0 if outcomes[d["id"]] else 0.0) - d["shares"] * d["ask"] - d["fee"] for d in analyzed]
    groups = [d["group"] for d in analyzed]
    n_groups = len(set(groups))
    out = {"decisions": len(decisions), "resolved": len(resolved), "independent_decisions": n_groups,
           "analyzed_decisions": len(analyzed), "pending_groups": len(pending_groups),
           "win_rate": (sum(outcomes[d["id"]] for d in analyzed) / len(analyzed)) if analyzed else None,
           "paper_gate_met": n_groups >= PAPER_GATE, "sample_checkpoint_met": n_groups >= EVIDENCE_GATE,
           "evidence_gate_met": False, "interval_excludes_zero": False, "interval_above_zero": False,
           "duplicate_outcomes": duplicate_outcomes, "orphan_outcomes": orphan_outcomes, "strategies": strategies}
    if strategy is None and len(strategies) > 1:
        out["strategy_warning"] = "This journal mixes strategies, so they are pooled into one interval. Keep one journal per test, or pass a strategy."
    if pending_groups:
        out["pending_warning"] = (f"{len(pending_groups)} logged groups have not resolved. The groups analyzed are those that resolved first, "
                                  "which can differ from the whole sample; judge the sample you fixed only when every group in it has resolved.")
    if n_groups >= 2:
        mean, lo, hi = bootstrap_mean(pnl, groups, seed=seed)
        out["mean_net_pnl_per_decision"] = mean
        if len({outcomes[d["id"]] for d in analyzed}) < 2 or lo == hi:
            out.update({"ci95": None, "interval_warning": "No informative empirical interval: one outcome class or degenerate bootstrap. Model the missing tail before claiming an edge."})
        else:
            out.update({"ci95": (lo, hi), "interval_excludes_zero": lo > 0 or hi < 0,
                        "interval_above_zero": lo > 0, "evidence_gate_met": n_groups >= EVIDENCE_GATE and lo > 0 and not pending_groups})
    return out
