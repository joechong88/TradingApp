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
from datetime import datetime, date, UTC
import pytz
import time

from sqlalchemy.orm import Session
from db.models import SessionLocal, Trade
from utils.trades import calculate_pnl, trades_to_df, get_qm, build_trade_label
from utils.market_clock import show_market_clock
from utils.formatters import format_currency, format_pnl, format_datetime, pnl_color, expiry_color
from utils.logger import get_logger
from utils.quote_manager import QuoteManager

# --- Initiate logging
logger = get_logger(__name__)
logger.debug("Starting Open Trades page")

# --- Initialize QuoteManager
if "qm" not in st.session_state:
    st.session_state.qm = QuoteManager()

compact_mode = st.sidebar.toggle("Compact Mode", value=True)

def get_qm(force_new=False):
    global _qm
    if force_new or _qm is None:
        _qm = QuoteManager()
    
    return _qm

def fetch_trades():
    with SessionLocal() as db:  # type: Session
        trades = db.query(Trade).order_by(Trade.id.desc()).all()
        return trades

if "exit_date" not in st.session_state:
    st.session_state.exit_date = datetime.now(UTC).date()
if "exit_time" not in st.session_state:
    st.session_state.exit_time = "16:00:00"

# --- Utility: Load and preprocess open trades ---
#@st.cache_data(ttl=60)   # cache for 60 seconds
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

    return open_df

def update_expiry_in_db(trade_id: int, new_expiry: str):
    """
    Update the expiry_dt field for a given trade.
    new_expiry must be a string in YYYYMMDD format.
    """
    with SessionLocal() as db:
        trade = db.get(Trade, trade_id)
        if trade is None:
            return False  # or raise an exception if you prefer

        trade.expiry_dt = new_expiry
        db.commit()
        return True

def render_trade_table(styled_df, compact_mode: bool = False):
    """
    Renders two coordinated tables:
    1. A visually formatted HTML table (Styler colors, compact mode)
    2. An interactive st.data_editor table (renamed headers, sortable, resizable)

    Parameters:
        df (pd.DataFrame): The raw DataFrame (renamed columns)
        styled_df (pd.io.formats.style.Styler): The styled version of df
        compact_mode (bool): Whether to apply compact CSS
    """
    # --- 1. Render the interactive table (no Styler) ---
    st.data_editor(
        styled_df,
        width='stretch',
        hide_index=True,
        disabled=True,
        column_config={
            "Edit": st.column_config.TextColumn(
                "Edit",
                help="Click to edit expiry",
                disabled=False
            ),
            "trade_desc": "Trade Details",
            "option_last": st.column_config.NumberColumn("Option Price (Last)", format="$%0.2f"),
            "stock_last": st.column_config.NumberColumn("Stock Price (Last)", format="$%0.2f"),
            "entry_price": st.column_config.NumberColumn("Entry Price", format="$%0.2f"),
            "entry_commissions": st.column_config.NumberColumn("Entry Comm", format="$%0.2f"),
            "pnl": st.column_config.NumberColumn("P&L", width="150", format="$%0.2f"),
            "entry_dt": "Entry Date/Time",
            "exit_price": st.column_config.NumberColumn("Exit Price", format="$%0.2f"),
            "exit_commissions": st.column_config.NumberColumn("Exit Comm", format="$%0.2f"),
            "exit_dt": "Exit Date/Time",
            "strategy": "Strategy",
            "notes": "Notes",
            "units": st.column_config.NumberColumn("units", format="%0.2f"),
            "live_price": st.column_config.NumberColumn("Live Price", format="$%0.2f"),
            "option_bid": st.column_config.NumberColumn("Opt Bid", format="$%0.2f"),
            "option_ask": st.column_config.NumberColumn("Opt Ask", format="$%0.2f"),
            "stock_bid": st.column_config.NumberColumn("Stock Bid", format="$%0.2f"),
            "stock_ask": st.column_config.NumberColumn("Stock Ask", format="$%0.2f"),
            "itm_status": "ITM/OTM",
            "days_to_expiry": st.column_config.NumberColumn("Days to Expiry", format="%d"),
        }
    )

# --- Calculates the difference between the stock_last and strikeprice ---
#       and returns the CSS for the background colour
#
def itm_gradient(row):
    """
    Logic for the 'itm_status' column background color.
    """
    # Create an array of empty strings for the row
    colors = [''] * len(row)
    
    # Locate the index of the column we want to color
    try:
        itm_idx = row.index.get_loc('itm_status')
    except KeyError:
        return colors

    status = row.get('itm_status')
    stock = row.get('stock_last')
    strike = row.get('strikeprice')

    # Logic: Only color if ITM and values are valid
    if status == "ITM" and stock is not None and strike is not None:
        diff = abs(stock - strike)
        
        if diff < 1.0:
            bg = "#ff4b4b"  # Red (High risk/Near-the-money)
            text = "white"
        elif 1.0 <= diff <= 5.0:
            bg = "#ffaa00"  # Yellow/Orange
            text = "black"
        else:
            bg = "#28a745"  # Green (Deep ITM/Safe)
            text = "white"
            
        colors[itm_idx] = f'background-color: {bg}; color: {text}; font-weight: bold;'
    
    return colors

@st.dialog("Update Expiry Date")
def update_expiry_dialog(row):
    # Convert existing YYYYMMDD string → Python date
    raw_expiry = row["expiry_dt"]
    if raw_expiry is None:
        current = date.today()
    else:
        current = datetime.strptime(row["expiry_dt"], "%Y%m%d").date()

    new_date = st.date_input(
        "New Expiry Date",
        value=current,
        key=f"expiry_input_{row['id']}"
    )

    if st.button("Save"):
        new_expiry_str = new_date.strftime("%Y%m%d")
        update_expiry_in_db(row["id"], new_expiry_str)
        st.cache_data.clear()
        st.rerun()

### Main function starts here ###
# Create 2 columns for the Heading
col1, col2 = st.columns([2,1])  # adjust ratio for spacing
with col1:
    st.title("Open Trades")
with col2:
    # display the clock banner
    show_market_clock(mode="static")

if "refresh_nonce" not in st.session_state:
    st.session_state.refresh_nonce = 0

# time the execution
start = time.time()
logger.debug("fetch_trades() INITIATED")
trades = fetch_trades()
logger.debug("fetch_trades() took %.2f seconds", time.time()-start)

# 5. Convert to DataFrame using the refreshed QM
start = time.time()
logger.debug("trades_to_df() INITIATED")
df = trades_to_df(trades, live=True, qm=st.session_state.qm)   # this function will handle all the calculations and retrieval of the right data for stocks and options
df["trade_desc"] = df.apply(build_trade_label, axis=1) # apply the appropriate labels for closing trades later

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
        # --- 1. Apply the hidden column
        df_full = open_df.copy()
        hidden_cols = ["symbol", "strategy", "strikeprice", "expiry_dt"]
        df_view = df_full.drop(columns=hidden_cols)

        # --- 2. Re-order the columns, this must be done at the df, not the styler
        desired_order = [
            "trade_desc",
            "units",
            "pnl",
            "itm_status",
            "days_to_expiry",
            "option_last",
            "stock_last",
            "entry_price",
            "entry_commissions",
            "entry_dt",
            "exit_price",
            "exit_commissions",
            "exit_dt",
            "notes",
            "live_price",
            "option_bid",
            "option_ask",
            "stock_bid",
            "stock_ask"
        ]
        df_view2 = df_view[desired_order]

        # --- 2a. Calculate Aggregates, us from df_full
        if not df_full.empty:
            is_option = df_full["strikeprice"].notna()

            df_options = df_full[is_option]
            df_stocks = df_full[~is_option]

            opt_pnl = df_options["pnl"].sum()
            stk_pnl = df_stocks["pnl"].sum()

            opt_count = len(df_options)
            stk_count = len(df_stocks)

            total_open_pnl = opt_pnl + stk_pnl


        else:
            opt_pnl = stk_pnl = total_open_pnl = 0.0
            opt_count = stk_count = 0
            itm_count = 0
            total_trades = 0

        # --- 2b. Display the Top Dashboard Stats for Open Trades ---
        col_tot, col_stk, col_opt = st.columns(3)

        with col_tot:
            # Use delta to show color (Green for +, Red for -) automatically
            st.metric(
                label = "Total Open Trades P&L",
                value = f"${total_open_pnl:,.2f}",
                delta = f"${total_open_pnl:,.2f}"
            )
        with col_stk:
            st.metric(
                label = "Stocks P&L",
                value = f"${stk_pnl:,.2f}",
                delta = f"{stk_count} Positions",
                delta_color = "off"
            )
        with col_opt:
            st.metric(
                label = "Options P&L",
                value = f"${opt_pnl:,.2f}",
                delta = f"{opt_count} Positions",
                delta_color = "off"
            )
        st.divider()

        # --- 3. Styled them accordingly, before sending to rendering the table
        start = time.time()
        logger.debug("open_df styling INITIATED")
        styled_df = df_view2.style.format({
            "option_last": "${:,.2f}",
            "stock_last": "${:,.2f}",
            "entry_price": "${:,.2f}",
            "entry_commissions": "${:,.2f}",
            "pnl": "${:,.2f}",
            "days_to_expiry": "{:,.0f}"
        }).set_properties(
            subset=["option_last", "stock_last", "entry_price", "entry_commissions", "pnl"],
            **{"text-align": "right"}
        ).map(pnl_color, subset="pnl").map(expiry_color, subset="days_to_expiry").apply(itm_gradient, axis=1)
        logger.debug("open_df styling took %.2f seconds", time.time()-start)
        render_trade_table(styled_df, compact_mode)

        st.divider()
        st.subheader("Close an open trade")
        
        # Use the label in your selectbox, but return the id
        trade_map = dict(zip(open_df["trade_desc"], open_df["id"]))
        sel_label = st.selectbox("Select trade ID to close", list(trade_map.keys()))
        sel_id = trade_map[sel_label]
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