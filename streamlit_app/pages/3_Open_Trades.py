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
from utils.trades import calculate_pnl, trades_to_df, get_qm
from utils.market_clock import show_market_clock
from utils.formatters import format_currency, format_pnl, format_datetime, pnl_color, expiry_color
from utils.logger import get_logger

# --- Initiate logging
logger = get_logger(__name__)
logger.debug("Starting Open Trades page")

qm = get_qm()
# qm.cancel_all()  # optional: clear previous subs on entering Open Trades

@st.cache_data(ttl=60)
def fetch_trades():
    with SessionLocal() as db:  # type: Session
        trades = db.query(Trade).order_by(Trade.id.desc()).all()
        return trades

if "exit_date" not in st.session_state:
    st.session_state.exit_date = datetime.now(UTC).date()
if "exit_time" not in st.session_state:
    st.session_state.exit_time = "16:00:00"

# --- Utility: Load and preprocess open trades ---
@st.cache_data(ttl=60)   # cache for 60 seconds
def load_open_trades(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return pd.DataFrame()

    open_df = trades_df[trades_df["is_open"] == True].copy()

    # Format entry datetime
    if "entry_dt" in open_df.columns:
        open_df["entry_dt"] = open_df["entry_dt"].apply(format_datetime)

    # Ensure numeric types
    for col in ["option_last","stock_last","entry_price","strikeprice",
                "entry_commissions","pnl"]:
        open_df[col] = pd.to_numeric(open_df[col], errors="coerce")

    # Expiry calculations
    open_df["expiry_date"] = pd.to_datetime(open_df["expiry_dt"], format="%Y%m%d", errors="coerce")
    eastern = pytz.timezone("US/Eastern")
    today_et = pd.Timestamp(datetime.now(eastern).date())
    open_df["days_to_expiry"] = (open_df["expiry_date"] - today_et).dt.days.clip(lower=0)

    # Re-order columns
    cols_order = ["id","symbol","strategy","strikeprice", "expiry_dt", "days_to_expiry", "units", "pnl", "entry_price", "option_last","stock_last"] + [
        c for c in open_df.columns if c not in ["id","symbol","strategy","strikeprice", "expiry_dt", "days_to_expiry", "units", "entry_price", "option_last","stock_last","pnl","days_to_expiry"]
    ]
    return open_df[cols_order]

### Main function starts here ###
# Create 2 columns for the Heading
col1, col2 = st.columns([2,1])  # adjust ratio for spacing
with col1:
    st.title("Open Trades")
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
df = trades_to_df(trades, live=True)   # this function will handle all the calculations and retrieval of the right data for stocks and options
logger.debug("trades_to_df() took %.2f seconds", time.time()-start)

if df.empty:
    st.warning("No trades found in the database.")
    open_df = pd.DataFrame()
else:
    start = time.time()
    logger.debug("load_open_trades() INITIATED")
    open_df = load_open_trades(df)
    logger.debug("load_open_trades() took %.2f seconds", time.time()-start)

st.subheader("Open trades")
if open_df.empty:
    st.info("No open trades.")
else:
    # Apply styling to fields
    start = time.time()
    logger.debug("open_df styling INITIATED")
    styled_df = open_df.style.format({
        "option_last": "${:,.2f}",
        "stock_last": "${:,.2f}",
        "entry_price": "${:,.2f}",
        "strikeprice": "${:,.2f}",
        "entry_commissions": "${:,.2f}",
        "pnl": "${:,.2f}",
        "days_to_expiry": "{:,.0f}"
    }).set_properties(
        subset=["option_last", "stock_last", "entry_price", "strikeprice", "entry_commissions", "pnl"],
        **{"text-align": "right"}
    ).map(pnl_color, subset="pnl").map(expiry_color, subset="days_to_expiry")
    logger.debug("open_df styling took %.2f seconds", time.time()-start)

    # Rename the header
    st.dataframe(
        styled_df, 
        use_container_width=True,
        column_config={
            "symbol": "Ticker",
            "option_last": st.column_config.NumberColumn("Option Price (Last)", format="$%0.2f"),
            "stock_last": st.column_config.NumberColumn("Stock Price (Last)", format="$%0.2f"),
            "entry_price": st.column_config.NumberColumn("Entry Price", format="$%0.2f"),
            "entry_commissions": st.column_config.NumberColumn("Entry Commissions", format="$%0.2f"),
            "strikeprice": st.column_config.NumberColumn("Strike Price", format="$%0.2f"),
            "pnl": st.column_config.NumberColumn("P&L", format="$%0.2f"),
            "entry_dt": "Entry Date/Time",
            "exit_price": st.column_config.NumberColumn("Exit Price", format="$%0.2f"),
            "exit_commissions": st.column_config.NumberColumn("Exit Commissions", format="$%0.2f"),
            "exit_dt": "Exit Date/Time",
            "strategy": "Strategy",
            "notes": "Notes",
            "is_open": None,
            "units": st.column_config.NumberColumn("Position", format="%0.2f"),
            "live_price": st.column_config.NumberColumn("Live Price", format="$%0.2f"),
            "option_bid": st.column_config.NumberColumn("Opt Bid", format="$%0.2f"),
            "option_ask": st.column_config.NumberColumn("Opt Ask", format="$%0.2f"),
            "stock_bid": st.column_config.NumberColumn("Stock Bid", format="$%0.2f"),
            "stock_ask": st.column_config.NumberColumn("Stock Ask", format="$%0.2f"),
            "itm_status": "ITM/OTM",
            "days_to_expiry": st.column_config.NumberColumn("Days to Expiry", format="%d")
        }
    )

    st.divider()
    st.subheader("Close an open trade")
    sel_id = st.selectbox("Select trade ID to close", open_df["id"].tolist())
    exit_price = st.number_input("Exit price", min_value=0.0, step=0.01)
    exit_commissions = st.number_input("Exit Commissions", min_value=0.0, step=0.01)

    st.date_input("Exit date (ET assumed)", key="exit_date")
    st.text_input("Exit time (HH:MM:SS) (ET assumed)", key="exit_time")

    if st.button("Close trade"):
        with SessionLocal() as db:  # type: Session
            t = db.query(Trade).filter(Trade.id == sel_id).first()
            if not t:
                st.error("Trade not found.")
            else:
                exit_dt = datetime.combine(
                    st.session_state.exit_date,
                    datetime.strptime(st.session_state.exit_time, "%H:%M:%S").time()
                )
                t.exit_price = exit_price
                t.exit_dt = exit_dt
                t.exit_commissions = exit_commissions
                t.is_open = False
                db.commit()
                st.success(f"Trade {sel_id} closed.")