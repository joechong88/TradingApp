from src.trading_app.strategies.example_strategy import SMACrossover
import pandas as pd


def test_sma_signals_basic():
    # create a price series where short MA crosses above long MA
    prices = pd.Series([1.0]*20 + [2.0]*40)
    strat = SMACrossover(short_window=3, long_window=5)
    sig = strat.signals(prices)
    # After the step up, expect long signals (1) for later indexes
    assert (sig.iloc[-10:] == 1).any()
