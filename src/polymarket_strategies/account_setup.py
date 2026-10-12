"""Easy local account setup: an optional private credentials file and a readiness check. No value is ever printed."""
from __future__ import annotations

import asyncio
import os
import re
import stat
import tempfile

from . import safety

CREDENTIAL_NAMES = ("POLYMARKET_WALLET_ADDRESS", "POLYMARKET_SIGNER_PRIVATE_KEY", "POLYMARKET_API_KEY",
                    "POLYMARKET_API_SECRET", "POLYMARKET_API_PASSPHRASE")


def credentials_file():
    return safety.state_dir() / "credentials.env"


def read_saved() -> dict:
    """The saved NAME=value lines, refused unless the file is a regular file that only you can read."""
    path = credentials_file()
    if not os.path.lexists(path):
        return {}
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{path} must be a regular file, not a folder or a link")
    if os.name == "posix" and info.st_mode & 0o077:
        raise ValueError(f"{path} can be read by other users; run: chmod 600 {path}")
    values = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, _, value = line.partition("=")
        if name.strip() not in CREDENTIAL_NAMES or not value.strip():
            raise ValueError(f"{path} line {number}: expected NAME=value for one of the five account values")
        values[name.strip()] = value.strip()
    return values


def load_saved() -> list[str]:
    """Put the saved values into this process's environment (a value already there wins). Returns the names loaded."""
    loaded = []
    for name, value in read_saved().items():
        if not os.environ.get(name):
            os.environ[name] = value
            loaded.append(name)
    return loaded


def save(values: dict) -> None:
    """Write the credentials file, readable only by you; a half-written file never replaces a good one."""
    path = credentials_file()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".credentials-")  # created readable only by you
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write("# Polymarket account values for polymarket-strategies. Keep private: never share or commit this file.\n")
            out.writelines(f"{name}={values[name]}\n" for name in CREDENTIAL_NAMES if name in values)
        os.replace(temp, path)
    except BaseException:
        if os.path.lexists(temp):
            os.unlink(temp)
        raise


async def check(saved=(), *, offline: bool = False) -> dict:
    """Is the account ready? Local facts first; unless offline, also the location check and a read-only look at your pUSD."""
    items, problems = {}, []
    for name in CREDENTIAL_NAMES:
        if os.environ.get(name):
            items[name] = "set (saved file)" if name in saved else "set (environment)"
        else:
            items[name] = "MISSING"
            problems.append(f"{name} is missing: run `trade setup`")
    wallet, key = os.environ.get(CREDENTIAL_NAMES[0], ""), os.environ.get(CREDENTIAL_NAMES[1], "")
    if wallet and not re.fullmatch(r"0x[0-9a-fA-F]{40}", wallet):
        problems.append("POLYMARKET_WALLET_ADDRESS must be 0x followed by 40 hexadecimal characters")
    elif wallet and key:
        try:
            from eth_account import Account
            items["wallet"] = ("the signer's own address" if Account.from_key(key).address.lower() == wallet.lower()
                               else "a smart wallet that the signer controls")
        except Exception:
            problems.append("POLYMARKET_SIGNER_PRIVATE_KEY is not a valid private key")
    items["live_flag"] = ("set" if os.environ.get("POLYMARKET_STRATEGIES_LIVE") == "1"
                          else "not set: `export POLYMARKET_STRATEGIES_LIVE=1` before `trade submit`")
    for path in safety.kill_files():
        if os.path.lexists(path):
            problems.append(f"kill switch engaged: delete {path} to resume new orders")
    if not offline:
        try:
            blocked = (await asyncio.to_thread(safety.geoblock_status)).get("blocked") is not False
            items["location"] = "NOT allowed to place orders (Polymarket geoblock)" if blocked else "allowed"
            if blocked:
                problems.append("orders are not allowed from this location (Polymarket geoblock)")
        except Exception:
            problems.append("the location (geoblock) check could not reach Polymarket")
        if not problems:
            from . import execution
            try:
                items["account"] = account = await execution.pusd_balance()
            except execution.ExecutionError as error:
                problems.append(str(error))
            else:
                if float(account["pusd_balance"]) <= 0:
                    problems.append("the wallet holds no pUSD: fund it on Polymarket first")
                if not any(float(value) > 0 for value in account["pusd_allowance_by_exchange"].values()):
                    problems.append("no exchange is allowed to spend your pUSD: grant the approvals with the SDK's setup_trading_approvals() (TRADING.md, section 4)")
    return {"ready": not problems, "items": items, "problems": problems}
