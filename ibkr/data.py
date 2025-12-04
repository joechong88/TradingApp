from typing import Dict, Any
import asyncio

# --- Ensure an event loop exists in Streamlit's script thread ---
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from ib_insync import Stock, IB, util
import pandas as pd
from datetime import datetime, UTC
from .connection import connect_ib

def stock_contract(symbol: str, exchange: str = "SMART", currency: str = "USD") -> Stock:
    return Stock(symbol, exchange, currency)

def get_live_quote(symbol: str) -> Dict[str, Any]:
    ib: IB = connect_ib()
    contract = stock_contract(symbol)
    ticker = ib.reqMktData(contract, "", False, False)
    ib.sleep(1)

    last_price = ticker.last or ticker.close or 0.0
    bid_price = ticker.bid or 0.0
    ask_price = ticker.ask or 0.0

    return {
        "symbol": symbol,
        "bid": bid_price,
        "ask": ask_price,
        "last": last_price,
        "close": ticker.close,
        "time": util.parseIBDatetime(ticker.time) if ticker.time else datetime.now(UTC),
    }

def get_historical_ohlc(symbol: str, duration_str="2 D", bar_size="5 mins") -> pd.DataFrame:
    ib: IB = connect_ib()
    contract = stock_contract(symbol)
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=duration_str,
        barSizeSetting=bar_size,
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
    )
    df = util.df(bars)
    if not df.empty:
        df.rename(columns={
            "date": "Date", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "volume": "Volume"
        }, inplace=True)
        df.set_index("Date", inplace=True)
    return df

def calc_pdh_pdl(df: pd.DataFrame) -> Dict[str, float]:
    if df.empty:
        return {"PDH": None, "PDL": None}
    dates = pd.to_datetime(df.index).date
    last_day = dates[-1]
    prev_mask = dates != last_day
    prev_df = df[prev_mask] if prev_mask.any() else df.iloc[:-1]
    if prev_df.empty:
        return {"PDH": None, "PDL": None}
    return {"PDH": float(prev_df["High"].max()), "PDL": float(prev_df["Low"].min())}