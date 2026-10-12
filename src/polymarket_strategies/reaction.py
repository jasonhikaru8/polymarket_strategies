"""How fast does a price move after news, and what is a fade worth? Pure arithmetic on a price history you supply.

`reaction` reads a list of (epoch_seconds, price) samples around a scheduled release and reports the price before it and the price after
each checkpoint. `fade_value` prices the bet that a spike is a false alarm. Chapter 11 of the book uses both, with real data captured
for the book. The reader exercise uses made-up prices. No network access here.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right


def reaction(history: list[tuple[float, float]], release: float, checkpoints: tuple[int, ...] = (60, 300, 3600)) -> dict:
    """`history` is sorted by time; `release` is the epoch second of the news.

    before: the last sample at or before the release.
    after[c]: the first sample at or after release + c seconds (samples come about once a minute, so 'after 60 seconds' means the first
        sample that is at least 60 seconds late).
    move[c]: after[c] minus before. share_of_last_move[c]: move[c] over the move at the last checkpoint (None if that move is zero).
    """
    times = [t for t, _ in history]
    i = bisect_right(times, release) - 1
    before = history[i] if i >= 0 else None
    after, move, share = {}, {}, {}
    for c in checkpoints:
        j = bisect_left(times, release + c)
        after[c] = history[j] if j < len(history) else None
    last = after[checkpoints[-1]]
    for c in checkpoints:
        if before is None or after[c] is None:
            move[c] = share[c] = None
            continue
        move[c] = after[c][1] - before[1]
        total = None if last is None else last[1] - before[1]
        share[c] = None if not total else move[c] / total
    return {"before": before, "after": after, "move": move, "share_of_last_move": share}


def implied_chance_true(pre: float, post: float) -> float:
    """A rumor lifts a share from `pre` to `post`. If the rumor is confirmed the share goes to 1; if it is denied it returns to `pre`.
    The price then says: post = p * 1 + (1 - p) * pre, so the market's chance that the rumor is true is (post - pre) / (1 - pre)."""
    return (post - pre) / (1 - pre)


def fade_value(pre: float, post: float, belief_true: float) -> float:
    """Expected profit per share of fading the spike (buying NO at 1 - post), given your own chance that the rumor is true.
    Denied: NO is worth 1 - pre, a gain of post - pre. Confirmed: NO is worth 0, a loss of 1 - post. Before fees and spread."""
    return (1 - belief_true) * (post - pre) - belief_true * (1 - post)
