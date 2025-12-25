import pandas as pd
import logging
import streamlit as st
import time
import threading
from typing import Dict, List
from db.models import Trade
from utils.logger import get_logger
from utils.quote_manager import QuoteManager

@st.cache_resource(show_spinner=False)
def get_qm() -> QuoteManager:
    """
    Return a singleton QuoteManager per Streamlit session.
    QuoteManager itself handles reconnection and subscriptions.
    """
    return QuoteManager()

# --- Initiate logging
logger = get_logger(__name__)

def calculate_pnl(data, live_price: float = None) -> float:
    """
    Unified P&L calculator for both Trade objects and DataFrame rows.
    Handles Stocks (1x) and Options (100x).
    """
    # 1. Handle Input Type (Object vs Dictionary/Row)
    # This allows the function to work with trade_obj.attribute or row['column']
    if hasattr(data, "__getitem__"):  # It's a dict or pandas row
        entry_price = data.get("entry_price")
        exit_price = data.get("exit_price")
        units = data.get("units")
        entry_comm = data.get("entry_commissions", 0) or 0
        exit_comm = data.get("exit_commissions", 0) or 0
        strategy = str(data.get("strategy", "")).lower().strip()
        has_option_attrs = data.get("strikeprice") and data.get("expiry_dt")
    else:  # It's a Trade class object
        entry_price = data.entry_price
        exit_price = data.exit_price
        units = data.units
        entry_comm = data.entry_commissions or 0
        exit_comm = data.exit_commissions or 0
        strategy = str(getattr(data, "strategy", "")).lower().strip()
        has_option_attrs = getattr(data, "strikeprice", None) and getattr(data, "expiry_dt", None)

    # 2. Determine Exit/Live Price
    price_out = live_price if live_price is not None else exit_price
    
    if price_out is None or entry_price is None:
        return 0.0

    # 3. Determine Multiplier
    # Logic: If specifically 'long'/'short' -> Stock. 
    # Otherwise, if it has option attributes -> Option.
    if strategy in ["long", "short"]:
        multiplier = 1
    elif has_option_attrs or strategy not in ["", "none"]:
        multiplier = 100
    else:
        multiplier = 1  # Default fallback to Stock

    # 4. Final Calculation
    gross_pnl = (price_out - entry_price) * units * multiplier
    net_pnl = gross_pnl - entry_comm - exit_comm
    
    return net_pnl

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

def safe_option_price(opt_quote: dict, trade) -> float | None:
    """
    Return option last price if available, otherwise fallback to stored exit/entry or cached close.
    """
    last = opt_quote.get("last")
    if last is not None:
        return last

    # Fallback: use exit_price if trade is closed, else entry_price as proxy
    if trade.exit_price:
        return trade.exit_price
    return trade.entry_price

# Utility function to built the trade's label to be populated in the Close Trade selection box  
def build_trade_label(row):
    # Base: symbol + strategy
    label = f"{row['symbol']} — {row['strategy']}"

    # If it's an option, append expiry + strike
    if row.get("expiry_dt") and row.get("strikeprice"):
        # Determine the right (C or P) based on strategy
        strategy_lower = row["strategy"].lower()
        right = "P" if strategy_lower.startswith("csp") else "C"

        expiry = row["expiry_dt"]
        strike = row["strikeprice"]
        label = f"{row['symbol']} {expiry} {strike}{right} — {row['strategy']}"

    return label

def trades_to_df(trades: List[Trade], live: bool = True, qm=None) -> pd.DataFrame:
    """
    Convert a list of Trade objects into a Pandas DataFrame.
    - live=True: fetch IBKR live quotes for open trades.
    - live=False: skip IBKR calls, use only stored DB values.
    Ensures all expected columns exist, even if trades is empty.
    """
    rows = []
    for t in trades:
        # Default values
        option_last = option_bid = option_ask = None
        stock_last = stock_bid = stock_ask = None

        # Determine live price if trade  is open
        live_price = None
        itm_status = None

        if live and t.is_open:
            if qm is not None:
                if t.strikeprice and t.expiry_dt:
                    #Option trade -> use option_last
                    right = "P" if t.strategy.lower().startswith("csp") else "C"
                    expiry_dt = str(t.expiry_dt)
                    strikeprice = float(t.strikeprice)

                    start = time.time()
                    logger.debug("Fetching live option quote for %s %s %s%s", t.symbol, expiry_dt, strikeprice, right)
                    try:
                        opt_quote = qm.safe_get_quote(
                            symbol      = t.symbol,
                            exchange    = "SMART",
                            currency    = "USD",
                            expiry      = expiry_dt,
                            strike      = strikeprice,
                            right       = right
                        )
                        logger.debug("get_quote() took %.2f seconds", time.time()-start)

                        if opt_quote:
                            option_last = opt_quote.get("last")
                            live_price = option_last
                            logger.debug("Received option quote for %s %s %s%s: %s", t.symbol, expiry_dt, strikeprice, right, option_last)
                        else:
                            option_last = None
                            logger.warning("No option quote for %s %s %s%s (opt_quote is None)", t.symbol, expiry_dt, strikeprice, right)

                    except Exception as e:
                        logger.error("Option quote failed for %s: %s", t.symbol, e)

                    # also fetch underlying stock quote
                    start = time.time()
                    logger.debug("Fetching live stock quote (in options) for %s", t.symbol)
                    try:                    
                        stock_quote = qm.safe_get_quote(
                            symbol      = t.symbol
                        )
                        logger.debug("get_quote() took %.2f seconds", time.time()-start)

                        if stock_quote:
                            stock_last = stock_quote.get("last")
                            stock_bid = stock_quote.get("bid")
                            stock_ask = stock_quote.get("ask")
                            logger.debug("Received stock quote (in options) for %s: %s", t.symbol, stock_last)
                        else:
                            stock_last = stock_bid = stock_ask = None
                    except Exception as e:
                        logger.error("Stock quote failed for %s: %s", t.symbol, e)

                    # ITM/OTM logic
                    if stock_last is not None:
                        if right == "P":
                            itm_status = "ITM" if stock_last < t.strikeprice else "OTM"
                        else: # Call
                            itm_status = "ITM" if stock_last > t.strikeprice else "OTM"
                else:
                    # Stock trade -> use stock_last
                    start = time.time()
                    logger.debug("Fetching live stock quote for %s", t.symbol)
                    try:
                        stock_quote = qm.safe_get_quote(
                            symbol      = t.symbol
                        )
                        logger.debug("get_quote() took %.2f seconds", time.time()-start)
                        stock_last = stock_quote.get("last")
                        stock_bid = stock_quote.get("bid")
                        stock_ask = stock_quote.get("ask")
                        live_price = stock_last
                        logger.debug("Received stock quote for %s: %s", t.symbol, stock_last)
                    except Exception as e:
                        logger.error("Stock quote failed for %s: %s", t.symbol, e)

        # Build row
        rows.append({
            "id": t.id,
            "symbol": t.symbol,
            "strategy": t.strategy,
            "units": t.units,
            "strikeprice": t.strikeprice,
            "expiry_dt": str(t.expiry_dt) if t.expiry_dt else None,
            "entry_price": t.entry_price,
            "expected_rr": t.expected_rr,
            "entry_dt": t.entry_dt,
            "entry_commissions": t.entry_commissions,
            "is_open": t.is_open,
            "exit_price": t.exit_price,
            "exit_dt": t.exit_dt,
            "exit_commissions": t.exit_commissions,
            "notes": t.notes,
            "option_last": option_last,
            "option_bid": option_bid,
            "option_ask": option_ask,
            "stock_last": stock_last,
            "stock_bid": stock_bid,
            "stock_ask": stock_ask,
            "itm_status": itm_status,
            "live_price": live_price,
            "pnl": calculate_pnl(t, live_price=live_price)  # unified P&L in dataframe
        })

    # Define all expected columns' header
    columns = [
        "id", "symbol", "strategy", "units", "strikeprice", "expiry_dt",
        "entry_price", "expected_rr", "entry_dt", "entry_commissions",
        "is_open", "exit_price", "exit_dt", "exit_commissions", "notes", 
        "option_last", "option_bid", "option_ask", "stock_last", "stock_bid", "stock_ask",
        "itm_status", "live_price", "pnl"
    ]

    return pd.DataFrame(rows, columns=columns)

def compute_trade_duration(df, entry_col="entry_dt", exit_col="exit_dt"):
    """
    Adds a 'duration' column showing the time spent in the trade
    as a human-readable string (Xd Yh Zm).
    """
    # Ensure datetime
    df[entry_col] = pd.to_datetime(df[entry_col])
    df[exit_col] = pd.to_datetime(df[exit_col])

    durations = []

    for entry, exit_ in zip(df[entry_col], df[exit_col]):
        delta = exit_ - entry

        total_minutes = int(delta.total_seconds() // 60)
        days = total_minutes // (24 * 60)
        hours = (total_minutes % (24 * 60)) // 60
        minutes = total_minutes % 60

        # Build readable string
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or (days == 0 and hours == 0):
            parts.append(f"{minutes}m")

        durations.append(" ".join(parts))

    df["duration"] = durations
    return df