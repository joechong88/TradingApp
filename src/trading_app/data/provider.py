from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Iterator


def fake_price_series(symbol: str, n: int = 200, seed: int | None = None) -> pd.Series:
    """Generate a fake price series for demonstration.

    Returns a pandas Series indexed by integer time steps.
    """
    rng = np.random.default_rng(seed)
    steps = rng.normal(loc=0.0005, scale=0.02, size=n).cumsum()
    base = 100 + steps
    return pd.Series(base, name=symbol)
