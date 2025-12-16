import pytest
import pandas as pd

# Import your IBKR data module
from ibkr import data

# --- Mock helpers ---
class MockIBKRClient:
    """Fake IBKR client for testing without hitting the real API."""
    def __init__(self):
        self.calls = []

    def get_market_data(self, symbol):
        self.calls.append(symbol)
        # Return fake data
        return {
            "symbol": symbol,
            "bid": 100.0,
            "ask": 101.0,
            "last": 100.5,
            "volume": 12345,
        }

    def get_historical_data(self, symbol, duration="1 D", bar_size="5 mins"):
        self.calls.append((symbol, duration, bar_size))
        # Return fake OHLC data
        return pd.DataFrame({
            "datetime": pd.date_range("2025-01-01", periods=3, freq="5min"),
            "open": [100, 101, 102],
            "high": [101, 102, 103],
            "low": [99, 100, 101],
            "close": [100.5, 101.5, 102.5],
            "volume": [1000, 1200, 1500],
        })

# --- Tests ---
def test_market_data_fetch(monkeypatch):
    client = MockIBKRClient()
    monkeypatch.setattr(data, "ibkr_client", client)

    result = data.fetch_market_data("AAPL")
    assert result["symbol"] == "AAPL"
    assert "bid" in result and "ask" in result
    assert client.calls == ["AAPL"]

def test_historical_data_fetch(monkeypatch):
    client = MockIBKRClient()
    monkeypatch.setattr(data, "ibkr_client", client)

    df = data.fetch_historical_data("MSFT", duration="1 D", bar_size="5 mins")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "open" in df.columns
    assert client.calls == [("MSFT", "1 D", "5 mins")]