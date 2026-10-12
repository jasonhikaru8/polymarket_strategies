"""Chapter 5 / Appendix D, an append-only journal demonstration with made-up decisions.

These are the twelve decisions in six linked groups behind the chapter's table. Uses a temporary file so rerunning the
exercise cannot mix demonstration rows into your own journal.
"""
from pathlib import Path
from tempfile import TemporaryDirectory

from polymarket_strategies import journal

# (group, ask, won): each fill is 10 shares and pays a 5-cent fee; fills in a group are added together
PLAN = [("g1", 0.42, False), ("g1", 0.30, False), ("g2", 0.55, True), ("g3", 0.60, True), ("g3", 0.20, False),
        ("g4", 0.35, False), ("g5", 0.70, True), ("g5", 0.45, True), ("g5", 0.25, False), ("g6", 0.50, True),
        ("g6", 0.38, False), ("g6", 0.65, True)]

with TemporaryDirectory() as folder:
    path = Path(folder) / "demo.jsonl"
    for number, (group, ask, won) in enumerate(PLAN):
        decision = journal.log_decision(path, strategy="demo", market=f"made-up-question-{number}",
                                        group=group, ask=ask, shares=10, fee=0.05)
        journal.log_outcome(path, decision, won=won)
    summary = journal.summarize(path)
    print({key: round(value, 4) if isinstance(value, float) else value for key, value in summary.items() if key != "ci95"})
    print("95% interval:", tuple(round(value, 2) for value in summary["ci95"]))
print("For your own test, log before the result is known and keep a permanent journal.")
