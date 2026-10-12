"""Strategy 30 (F1): Whale tracking and copy trading.

Run without arguments for a synthetic demonstration, --example for its input schema,
or --inputs FILE to analyze your own evidence. See STRATEGIES.md for execution scope.
The calculation lives in the shared strategy modules; this file fixes the book index.
"""
from polymarket_strategies.strategy_cli import entry_main


if __name__ == "__main__":
    entry_main(30)
