import asyncio
from utils.ui_components import render_top_metrics
import sys
import os

# 1. Get the absolute path to the directory two levels up from this file
# This takes you from streamlit_app/pages/ -> streamlit_app/ -> Root
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))

# 2. Add that root path to sys.path so 'db' and 'utils' can be found
if root_path not in sys.path:
    sys.path.insert(0, root_path)

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
import matplotlib

from sqlalchemy.orm import Session
from db.models import SessionLocal, Trade
from utils.trades import trades_to_df, get_qm, build_trade_label, get_all_open_positions
from utils.market_clock import show_market_clock
from utils.formatters import format_currency, format_pnl, format_datetime
from utils.logger import get_logger
from utils.quote_manager import QuoteManager
from utils.ui_components import get_styled_trade_df, render_close_trade_form, render_complex_strategy_cards, roll_short_call_dialog

# --- Initiate logging
logger = get_logger(__name__)
logger.debug("Starting Open Trades page")

# --- Initialize QuoteManager
if "qm" not in st.session_state:
    st.session_state.qm = QuoteManager()

# Initialize the refresh counter in session state if it doesn't exist
if "refresh_count" not in st.session_state:
    st.session_state.refresh_count = 0

if "exit_date" not in st.session_state:
    st.session_state.exit_date = datetime.now(UTC).date()
if "exit_time" not in st.session_state:
    st.session_state.exit_time = "16:00:00"

if "last_updated_dt" not in st.session_state:
    st.session_state.last_updated_dt = None

# Sidebar Refresh Button
with st.sidebar:
    if st.sidebar.button("🔄 Refresh Live Quotes", width='stretch'):
        st.session_state.refresh_count += 1
        # No need for st.rerun() as the button click triggers a rerun automatically
        st.session_state.last_updated_dt = datetime.now(UTC)

    if isinstance(st.session_state.last_updated_dt, datetime):
        # Obtain imestamp to current time (ET), and current KUL time
        tz_et = pytz.timezone('US/Eastern')
        tz_kul = pytz.timezone('Asia/Kuala_Lumpur')

        dt_et = st.session_state.last_updated_dt.astimezone(tz_et)
        dt_kul = st.session_state.last_updated_dt.astimezone(tz_kul)

        # Calculate age in seconds
        age_seconds = (datetime.now(UTC) - st.session_state.last_updated_dt).total_seconds()
        
        # Apply conditional coloring (Red if > 10 mins)
        time_color = "red" if age_seconds > 600 else "gray"
        
        st.caption(f"**Last Sync (Market):** {dt_et.strftime('%H:%M:%S')} ET")
        st.caption(f"**Last Sync (Local):** {dt_kul.strftime('%H:%M:%S')} KUL")

        if age_seconds > 600:
            st.error(f"⚠️ Quotes are {(age_seconds/60):.0f}m old")
    else:
        st.caption("No data synced yet.")

#@st.cache_data(ttl=90) # Cache live quotes for 60 seconds
@st.cache_data(show_spinner="Fetching live quotes data....")
def fetch_cached_positions(_qm, refresh_count):
    logger.debug("Fetching positions (Refresh Count: {refresh_count})")
    return get_all_open_positions(qm=_qm)

def get_qm(force_new=False):
    global _qm
    if force_new or _qm is None:
        _qm = QuoteManager()
    
    return _qm

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

# time the execution, retrieve data from database and obtain live quotes
start = time.time()
logger.debug("get_all_open_positions() INITIATED")
flat_trades, complex_groups = fetch_cached_positions(st.session_state.qm, st.session_state.refresh_count)
logger.debug("get_all_open_positions() took %.2f seconds", time.time()-start)

if st.session_state.last_updated_dt is None and not flat_trades.empty:
    st.session_state.last_updated_dt = datetime.now(UTC)

# Define Tabs
tab1, tab2 = st.tabs(["🎯 Single Leg", "🧬 Complex Strategies"])

with tab1:
    if not flat_trades.empty:
        flat_trades["trade_desc"] = flat_trades.apply(build_trade_label, axis=1) # apply the appropriate labels for closing trades later

        # Apply styling to fields
        # --- 1. Apply the hidden column
        df_full = flat_trades.copy()
        hidden_cols = ["symbol", "strategy", "strikeprice", "expiry_dt"]
        df_view = df_full.drop(columns=hidden_cols)

        # --- 2. Calculate Aggregates, use from df_full
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
        render_top_metrics(total_open_pnl, stk_pnl, stk_count, opt_pnl, opt_count)
        st.divider()

        # -- 3. Styled them accordingly, before sending to rendering the table
        start = time.time()
        logger.debug("Open Flat Trades styling INITIATED")
        if not df_view.empty:
            df_view = df_view.fillna({"live_price": 0.0, "pnl": 0.0, "pnl_pct": 0.0})
            styled_df, col_config = get_styled_trade_df(df_view, is_open=True)
        st.dataframe(
            styled_df,
            hide_index=True,
            width='stretch',
            column_config=col_config
        ) 
        logger.debug("Open Flat Trades styling took %.2f seconds", time.time()-start)
        st.divider()
        render_close_trade_form(flat_trades)
    else:
        st.info("No open trades.")
        flat_trades = pd.DataFrame()

with tab2:
    render_complex_strategy_cards(complex_groups)