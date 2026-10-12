"""Indexed strategy analyses and unapproved order-plan preparation; never authenticates."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
from uuid import uuid4

from . import strategy_catalog as catalog
from .jsonfile import read_json_text


def _index(value: str) -> int:
    for row in catalog.STRATEGIES:
        if value.upper() == row[1] or value == str(row[0]) or value == f"{row[0]:02d}":
            return row[0]
    raise argparse.ArgumentTypeError("Use a book number 1–35 or card ID such as C8")


def _read(path: str) -> dict:
    def nonfinite(value):
        raise ValueError("Nonfinite JSON numbers are not allowed")
    value = json.loads(read_json_text(path), parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError("Strategy inputs must be a JSON object")
    catalog.validate_inputs(value)
    return value


def _print(value):
    print(json.dumps(value, indent=2, allow_nan=False))


def prepare(index: int, inputs: dict, inspected_config: dict, *, min_edge: float | None = None, now=None) -> dict:
    """Attach real strategy parameters to a new, unapproved intent; never change a live intent."""
    meta = catalog.get(index)
    catalog.validate_inputs(inputs)
    catalog.validate_inputs(inspected_config)
    if meta["execution_mode"] != "forecast_order":
        raise ValueError("This method is analysis/proposal only; no executable strategy plan is supplied")
    if inputs.get("demo") is True:
        raise ValueError("Replace the synthetic example with real evidence and remove its demo marker")
    catalog.reject_placeholders(inputs)
    # The stricter of --min-edge and the min_edge written in the inputs file applies; with neither, 0.02.
    wanted = [value for value in (min_edge, inputs.get("min_edge")) if value is not None]
    for value in wanted:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not catalog.finite(value) or value < 0:
            raise ValueError("min_edge must be finite and nonnegative")
    min_edge = float(max(wanted)) if wanted else 0.02
    now = time.time() if now is None else now
    if not isinstance(inputs.get("as_of"), (int, float)) or not isinstance(inputs.get("valid_until"), (int, float)):
        raise ValueError("The inputs need numeric as_of and valid_until times (Unix seconds)")
    analysis = catalog.analyze(index, {**inputs, "min_edge": min_edge}, now=now)  # with the minimum edge that will apply
    if analysis["eligible"] is not True:
        raise ValueError("The inputs do not pass the strategy's own screen, so no plan was prepared: " + "; ".join(analysis["reasons"] or ["no reason given"]))
    if not isinstance(analysis.get("forecast"), dict):  # trade_decision needs it too: without it the preview could never accept this plan
        raise ValueError("The strategy's analysis gives no held-to-resolution forecast for an order, so no plan was prepared "
                         "(an exit-mark analysis is for tracking a position, not for placing a new order)")
    as_of, valid_until = inputs["as_of"], inputs["valid_until"]
    if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (as_of, valid_until))
            or not 0 <= as_of <= now < valid_until):
        raise ValueError("Strategy inputs must be dated, already available and still valid")
    config = json.loads(json.dumps(inspected_config, allow_nan=False))
    config["intent_id"] = str(uuid4())
    config["side"] = "BUY"
    if inputs.get("outcome") in ("YES", "NO"):
        config["outcome"] = inputs["outcome"]  # the analysis was run for this outcome (a Strategy 16 fade buys NO)
    config["strategy"] = {"kind": "indexed", "min_edge": min_edge,
                          "inputs": {"strategy_index": index, "parameters": json.loads(json.dumps(inputs, allow_nan=False))}}
    config["approval"]["approved"] = False
    config["approval"]["note"] = ""
    config["approval"]["reviewed_at"] = now
    config["approval"]["valid_until"] = min(config["approval"]["valid_until"], valid_until)
    # a fresh eleven-minute window from now (an older inspect file's own expiry would leave too little time to review, preview and submit),
    # never later than the forecast or the approval allows
    config["expires_at"] = min(int(now) + 660, int(valid_until), int(config["approval"]["valid_until"]))
    if config["expires_at"] < now + 185:
        raise ValueError("The forecast or approval window is too short for the GTD order workflow, which needs about three minutes after preparation; "
                         "if the inspected file is old, run `trade inspect` again")
    return config


def _save_plan(index: int, inputs_path: str, config_path: str, out: str, min_edge: float) -> None:
    from .trading_cli import load_config

    config = prepare(index, _read(inputs_path), load_config(config_path), min_edge=min_edge)
    with Path(out).open("x", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, allow_nan=False)
        handle.write("\n")
    _print({"strategy": catalog.get(index), "config_file": out, "approved": False,
            "next_step": "Read and approve the exact contract, set your limits, then use trade preview. Preparation has placed no order."})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="polymarket-strategies strategy", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="All 35 book numbers, card IDs, files and execution modes")
    example = sub.add_parser("example", help="Print the complete synthetic input schema")
    example.add_argument("index", type=_index)
    example.add_argument("--out", help="write the example to this new file (UTF-8) instead of printing it; an existing file is never overwritten")
    analyze = sub.add_parser("analyze", help="Analyze your input JSON without any account connection")
    analyze.add_argument("index", type=_index)
    analyze.add_argument("inputs")
    plan = sub.add_parser("prepare", help="Prepare a new unapproved intent for an eligible forecast method")
    plan.add_argument("index", type=_index)
    plan.add_argument("inputs")
    plan.add_argument("inspected_config")
    plan.add_argument("--out", required=True)
    plan.add_argument("--min-edge", type=float, help="minimum conservative edge per share; the stricter of this and the min_edge in your inputs file applies, and with neither it is 0.02 (an inputs file with a smaller min_edge makes the plan looser than that)")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            _print({"strategies": [catalog.get(i) for i in range(1, 36)]})
        elif args.command == "example":
            if args.out:
                try:
                    handle = Path(args.out).open("x", encoding="utf-8")  # never overwrite: a reader's edited inputs must survive a repeated command
                except FileExistsError:
                    parser.error(f"{args.out} already exists; choose a new name")
                with handle:
                    json.dump(catalog.example(args.index), handle, indent=2, allow_nan=False)
                    handle.write("\n")
                print(f"wrote {args.out}", file=sys.stderr)
            else:
                _print(catalog.example(args.index))
        elif args.command == "analyze":
            _print(catalog.analyze(args.index, _read(args.inputs)))
        else:
            _save_plan(args.index, args.inputs, args.inspected_config, args.out, args.min_edge)
    except (ValueError, KeyError, TypeError, OSError, OverflowError, RecursionError) as error:
        parser.error(str(error))


def entry_main(index: int, argv: list[str] | None = None) -> None:
    """Chapter filenames identify the strategy; their code shares the same tested methods."""
    meta = catalog.get(index)
    scope = "can feed a reviewed order plan" if meta["execution_mode"] == "forecast_order" else "analysis only: it cannot create an order plan"
    parser = argparse.ArgumentParser(description=f"Strategy {index} ({meta['id']}): {meta['name']}; {scope}.")
    parser.add_argument("--inputs", help="Analyze your documented JSON input; no credentials or orders")
    parser.add_argument("--example", action="store_true", help="Print a complete synthetic input object to edit")
    parser.add_argument("--trade-config", help="An existing inspected config; requires --inputs and --out")
    parser.add_argument("--out", help="Create an unapproved order plan; existing files are never overwritten")
    parser.add_argument("--min-edge", type=float, help="Minimum edge for an order plan; requires --trade-config")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.min_edge is not None and not args.trade_config:
            raise ValueError("--min-edge is an order-plan option and requires --trade-config")
        if args.example and (args.inputs or args.trade_config or args.out):
            raise ValueError("--example cannot be combined with input or order-plan options")
        if args.example:
            _print(catalog.example(index))
        elif args.trade_config or args.out:
            if not all((args.trade_config, args.out, args.inputs)):
                raise ValueError("Plan preparation requires --inputs, --trade-config and --out")
            _save_plan(index, args.inputs, args.trade_config, args.out, args.min_edge)
        elif args.inputs:
            _print(catalog.analyze(index, _read(args.inputs)))
        else:
            _print(catalog.analyze(index, catalog.example(index)))
    except (ValueError, KeyError, TypeError, OSError, OverflowError, RecursionError) as error:
        parser.error(str(error))
