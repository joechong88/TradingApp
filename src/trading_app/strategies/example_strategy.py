from __future__ import annotations
import pandas as pd


class SMACrossover:
    """Simple moving-average crossover strategy.

    Produces signals: 1 (long), -1 (short), 0 (flat)
    """

    def __init__(self, short_window: int = 10, long_window: int = 30):
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        self.short = short_window
        self.long = long_window

    def signals(self, prices: pd.Series) -> pd.Series:
        s = prices.rolling(self.short).mean()
        l = prices.rolling(self.long).mean()
        sig = pd.Series(0, index=prices.index)
        sig[s > l] = 1
        sig[s < l] = -1
        return sig
