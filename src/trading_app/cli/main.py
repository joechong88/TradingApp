from __future__ import annotations
import yaml
import argparse
from ..data.provider import fake_price_series
from ..strategies.example_strategy import SMACrossover


def run(symbol: str = "FAKE", short: int = 10, long: int = 30, n: int = 200):
    prices = fake_price_series(symbol, n=n, seed=42)
    strat = SMACrossover(short_window=short, long_window=long)
    sig = strat.signals(prices)
    print(f"Last price: {prices.iloc[-1]:.2f}")
    print(f"Last signal: {int(sig.iloc[-1])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="FAKE")
    parser.add_argument("--short", type=int, default=10)
    parser.add_argument("--long", type=int, default=30)
    parser.add_argument("--n", type=int, default=200)
    args = parser.parse_args()
    run(symbol=args.symbol, short=args.short, long=args.long, n=args.n)
