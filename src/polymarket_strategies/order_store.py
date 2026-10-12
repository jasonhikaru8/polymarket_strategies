"""Persistent order intents and observed fills. No signatures or credentials belong here."""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import stat
import time


def _private_file(path: Path) -> None:
    """Create the ledger as a private regular file; refuse a folder or a link instead of changing its permissions."""
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600))
        return
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("The ledger path must be a regular file, not a folder or a link.")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ValueError("The ledger file belongs to another user; choose a file of your own.")
    if info.st_size and path.open("rb").read(16) != b"SQLite format 3\x00":
        raise ValueError("That file is not an order ledger; the ledger path must be a new file or an existing ledger.")
    os.chmod(path, 0o600)


@contextmanager
def connection(path):
    path = Path(path)
    if str(path) == ":memory:":
        raise ValueError("The order ledger must be persistent.")
    _private_file(path)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS intents (
                intent_id TEXT PRIMARY KEY, account TEXT NOT NULL, plan_json TEXT NOT NULL,
                phase TEXT NOT NULL, order_id TEXT UNIQUE, order_status TEXT,
                created_at REAL NOT NULL, submitted_at REAL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fills (
                intent_id TEXT NOT NULL REFERENCES intents(intent_id), trade_id TEXT NOT NULL,
                role TEXT NOT NULL, size TEXT NOT NULL, price TEXT NOT NULL, status TEXT NOT NULL,
                fee_estimate TEXT NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY (intent_id, trade_id)
            );
        """)
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def _row(row):
    if row is None:
        raise ValueError("Intent not found in this ledger.")
    out = dict(row)
    out["plan"] = json.loads(out.pop("plan_json"))
    return out


def _missing(path) -> bool:
    """A ledger that does not exist yet. Reading one must not create it: a mistyped --ledger would leave a stray folder and empty database."""
    return str(path) != ":memory:" and not os.path.lexists(path)


def get(path, intent_id):
    if _missing(path):
        raise ValueError("No order ledger exists at that path; use the same --ledger as when the order was prepared "
                         "(the default is ~/.polymarket-strategies/orders.sqlite3).")
    with connection(path) as db:
        return _row(db.execute("SELECT * FROM intents WHERE intent_id=?", (intent_id,)).fetchone())


def reserve(path, account, plan):
    """Reserve before signing; duplicate and unresolved account intents cannot race."""
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM intents WHERE intent_id=?", (plan["intent_id"],)).fetchone():
            raise ValueError("This intent already exists; inspect it instead of resubmitting.")
        if db.execute("SELECT 1 FROM intents WHERE account=? AND phase IN ('PREPARING','SUBMITTING','UNKNOWN')", (account,)).fetchone():
            raise ValueError("This account has an unresolved intent; cancel preparation or reconcile it first.")
        now = time.time()
        db.execute("INSERT INTO intents(intent_id,account,plan_json,phase,created_at,updated_at) VALUES(?,?,?,'PREPARING',?,?)",
                   (plan["intent_id"], account, json.dumps(plan, sort_keys=True, allow_nan=False), now, now))


def transition(path, intent_id, phase, *, expected=None, order_id=None, order_status=None):
    if phase not in {"SUBMITTING", "ACCEPTED", "REJECTED", "UNKNOWN", "ABORTED", "CANCELED"}:
        raise ValueError("Unknown ledger phase.")
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = _row(db.execute("SELECT * FROM intents WHERE intent_id=?", (intent_id,)).fetchone())
        if expected is not None and row["phase"] != expected:
            raise ValueError("Intent changed state; no new order may be sent.")
        if phase == "SUBMITTING" and db.execute(
            "SELECT 1 FROM intents WHERE account=? AND intent_id<>? AND phase IN ('PREPARING','SUBMITTING','UNKNOWN')",
            (row["account"], intent_id),
        ).fetchone():
            raise ValueError("This account has another unresolved intent.")
        if row["order_status"] in {"CANCELED", "CANCELLED", "EXPIRED", "INVALID"}:
            # A delayed LIVE poll cannot resurrect an order whose terminal status is already recorded.
            order_status = row["order_status"]
            if phase == "ACCEPTED" and order_status != "INVALID":
                phase = "CANCELED"
        now = time.time()
        db.execute("UPDATE intents SET phase=?,order_id=COALESCE(?,order_id),order_status=COALESCE(?,order_status),submitted_at=?,updated_at=? WHERE intent_id=?",
                   (phase, order_id, order_status, now if phase == "SUBMITTING" else row["submitted_at"], now, intent_id))
        return _row(db.execute("SELECT * FROM intents WHERE intent_id=?", (intent_id,)).fetchone())


def save_fills(path, intent_id, fills, *, required_trade_ids=(), reported_matched=Decimal(0)):
    """Merge a complete observation atomically; filled economics and terminal states cannot change."""
    with connection(path) as db:
        db.execute("BEGIN IMMEDIATE")
        intent = _row(db.execute("SELECT * FROM intents WHERE intent_id=?", (intent_id,)).fetchone())
        saved = {row["trade_id"]: dict(row) for row in db.execute("SELECT * FROM fills WHERE intent_id=?", (intent_id,))}
        for fill in fills:
            old = saved.get(fill["trade_id"])
            if old is not None:
                if (fill["role"] != old["role"] or Decimal(fill["size"]) != Decimal(old["size"])
                        or Decimal(fill["price"]) != Decimal(old["price"])
                        or (old["status"] in {"CONFIRMED", "FAILED"} and fill["status"] != old["status"])):
                    raise ValueError("Trade update conflicts with previously observed economics or a terminal state.")
                if fill["updated_at"] < old["updated_at"]:
                    continue
            saved[fill["trade_id"]] = fill
            db.execute("""INSERT INTO fills VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(intent_id,trade_id) DO UPDATE SET status=excluded.status,
                fee_estimate=excluded.fee_estimate,updated_at=excluded.updated_at""",
                       (intent_id, fill["trade_id"], fill["role"], fill["size"], fill["price"], fill["status"], fill["fee_estimate"], fill["updated_at"]))
        if not set(required_trade_ids).issubset(saved):
            raise ValueError("Known associated trades have not appeared in the account history.")
        matched = sum((Decimal(fill["size"]) for fill in saved.values() if fill["status"] != "FAILED"), Decimal(0))
        if matched > Decimal(intent["plan"]["order"]["size"]):
            raise ValueError("Observed fills exceed the intended order size.")
        explained = sum((Decimal(fill["size"]) for fill in saved.values()), Decimal(0))
        if reported_matched > explained:
            raise ValueError("Reported matched quantity is not yet explained by the observed trade history.")


def fills(path, intent_id):
    if _missing(path):
        return []
    with connection(path) as db:
        return [dict(row) for row in db.execute("SELECT * FROM fills WHERE intent_id=? ORDER BY trade_id", (intent_id,))]


def summary(path):
    if _missing(path):
        return {"intents": [], "fills": []}
    with connection(path) as db:
        return {"intents": [_row(row) for row in db.execute("SELECT * FROM intents ORDER BY created_at")],
                "fills": [dict(row) for row in db.execute("SELECT * FROM fills ORDER BY intent_id,trade_id")]}
