import asyncio

# Ensure an event loop exists before anything else
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import logging  # for logging purposes
import streamlit as st
import pandas as pd
from datetime import datetime, UTC
import pytz
import time

from sqlalchemy.orm import Session
from db.models import SessionLocal, Trade
from utils.trades import trades_to_df, build_trade_label, compute_trade_duration
from utils.market_clock import show_market_clock
from utils.formatters import format_currency, format_pnl, format_datetime, pnl_color, expiry_color
from utils.logger import get_logger

@st.cache_data(ttl=60)
def fetch_trades():
    with SessionLocal() as db:  # type: Session
        trades = db.query(Trade).order_by(Trade.id.desc()).all()
        return trades

# --- Initiate logging
logger = get_logger(__name__)
logger.debug("Starting Closed Trades page")

if "exit_date" not in st.session_state:
    st.session_state.exit_date = datetime.now(UTC).date()
if "exit_time" not in st.session_state:
    st.session_state.exit_time = "16:00:00"

# --- Utility: Load and preprocess open trades ---
@st.cache_data(ttl=60)
def load_closed_trades(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()

    closed_df = trades_df[trades_df["is_open"] == False].copy()

    # Format entry/exit datetimes
    if "entry_dt" in closed_df.columns:
        closed_df["entry_dt"] = closed_df["entry_dt"].apply(format_datetime)
    if "exit_dt" in closed_df.columns:
        closed_df["exit_dt"] = closed_df["exit_dt"].apply(format_datetime)

    # Ensure numeric types
    for col in ["option_last", "stock_last", "entry_price","exit_price","strikeprice",
                "entry_commissions","exit_commissions","pnl"]:
        closed_df[col] = pd.to_numeric(closed_df[col], errors="coerce")

    closed_df = compute_trade_duration(closed_df)

    # Re-order columns: show PnL earlier
    cols_order = ["id", "symbol", "strategy", "pnl", "entry_price", "exit_price"] + [
                  c for c in closed_df.columns if c not in ["id", "symbol", "strategy", "pnl", "entry_price", "exit_price"]
    ]

    return closed_df[cols_order]

# Compute dynamic widths for columns that don't already have one
def compute_widths(df):
    widths = {}
    for col in df.columns:
        max_len = max(df[col].astype(str).map(len).max(), len(col))
        widths[col] = max(80, min(max_len * 8, 400))  # clamp for readability
    return widths

### Main function starts here ###
# Create 2 columns for the Heading
col1, col2 = st.columns([2,1])  # adjust ratio for spacing
with col1:
    st.title("Closed Trades")
with col2:
    # display the clock banner
    show_market_clock(mode="static")

# time the execution
start = time.time()
logger.debug("fetch_trades() INITIATED")
trades = fetch_trades()
logger.debug("fetch_trades() took %.2f seconds", time.time()-start)

start = time.time()
logger.debug("trades_to_df() INITIATED")
df = trades_to_df(trades, live=False)   # this function will handle all the calculations and retrieval of the right data for stocks and options
df["trade_desc"] = df.apply(build_trade_label, axis=1) # apply the appropriate labels for closing trades later
logger.debug("trades_to_df() took %.2f seconds", time.time()-start)

if df.empty:
    st.warning("No trades found in the database.")
    closed_df = pd.DataFrame()
else:
    start = time.time()
    logger.debug("load_closed_trades() INITIATED")
    closed_df = load_closed_trades(df)
    logger.debug("load_closed_trades() took %.2f seconds", time.time()-start)

st.subheader("Closed trades")
if closed_df.empty:
    st.info("No closed trades.")
else:
    start = time.time()
    logger.debug("closed_df styling INITIATED")

    # Apply styling to fields
    # --- 1. Apply the hidden column
    df_full = closed_df.copy()
    hidden_cols = [
        "symbol", "strategy", "strikeprice", "expiry_dt", "stock_last", "option_last",
        "live_price", "option_bid", "option_ask", "stock_bid", "stock_ask"
    ]
    df_view = df_full.drop(columns=hidden_cols)

    # --- 2. Re-order the columns, this must be done at the df, not the styler
    desired_order = [
        "trade_desc",
        "units",
        "pnl",
        "entry_price",
        "entry_commissions",
        "entry_dt",
        "exit_price",
        "exit_commissions",
        "exit_dt",
        "duration",
        "notes"
    ]
    df_view2 = df_view[desired_order]

    # sort by exit-date/time
    df_view2 = df_view2.sort_values("exit_dt", ascending=False)

    auto_widths = compute_widths(df_view2)
    base_config = {
        col: st.column_config.Column(width=auto_widths[col])
        for col in df_view2.columns
    }

    base_config.update({
        "trade_desc": "Trade Details",
        "units": st.column_config.NumberColumn("units", format="%0.2f"),
        "pnl": st.column_config.NumberColumn("P&L", format="$%0.2f"),
        "entry_price": st.column_config.NumberColumn("Entry Price", format="$%0.2f"),
        "entry_commissions": st.column_config.NumberColumn("Entry Comm", format="$%0.2f"),
        "entry_dt": "Entry Date/Time",
        "exit_price": st.column_config.NumberColumn("Exit Price", format="$%0.2f"),
        "exit_commissions": st.column_config.NumberColumn("Exit Comm", format="$%0.2f"),
        "exit_dt": "Exit Date/Time",
        "duration": "Duration", 
        "notes": "Notes"
    })

    styled_df = df_view2.style.format({
        "entry_price": "${:,.2f}",
        "entry_commissions": "${:,.2f}",
        "pnl": "${:,.2f}",
        "exit_price": "${:,.2f}",
        "exit_commissions": "${:,.2f}",
    }).set_properties(
        subset=["entry_price", "entry_commissions", "exit_price", "exit_commissions", "pnl", "duration"],
        **{"text-align": "right"}
    ).map(pnl_color, subset="pnl")
    logger.debug("closed_df styling took %.2f seconds", time.time()-start)

    st.dataframe(
        styled_df, 
        hide_index=True,
        width='stretch',
        column_config=base_config
    )