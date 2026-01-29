import asyncio
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
from datetime import datetime, UTC
import pytz
import time
from sqlalchemy.orm import Session

from db.models import SessionLocal, Trade
from utils.trades import trades_to_df, build_trade_label, compute_trade_duration, fetch_closed_complex_groups, calculate_comprehensive_pnl
from utils.market_clock import show_market_clock
from utils.formatters import format_currency, format_pnl, format_datetime, pnl_color, expiry_color
from utils.logger import get_logger
from utils.ui_components import get_styled_trade_df

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
                "entry_commissions","exit_commissions","pnl", "pnl_pct"]:
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

# --- Tabbed Interface ---
tab1, tab2 = st.tabs(["📊 Single Trades", "🏗️ Complex Strategies"])

with tab1:
    st.subheader("Closed Single-Leg Trades")

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

        if not df_view.empty:
            styled_df, col_config = get_styled_trade_df(df_view, is_open=False)

        st.dataframe(
            styled_df, 
            hide_index=True,
            width='stretch',
            column_config=col_config
        )
        logger.debug("closed_df styling took %.2f seconds", time.time()-start)

with tab2:
    st.subheader("Closed Complex Strategy History")
    closed_groups = fetch_closed_complex_groups()
    
    if not closed_groups:
        st.info("No closed complex strategies found.")
    else:
        for group in closed_groups:
            ticker = group.legs[0].symbol.strip() if group.legs else "Unknown"

            # Reuse your P&L engine - since it's closed, we pass empty active prices
            # The engine should naturally pull exit_price from the DB for closed legs
            stats = calculate_comprehensive_pnl(group.id, active_legs_data=[])

            # Use the actual TradeGroup timestamp
            closed_dt_str = format_datetime(group.updated_at) if group.updated_at else "N/A"
            note_preview = group.notes[:30] if group.notes else "No notes"
            pnl_val = stats['total_pnl']
            initial_cost = stats['initial_debit']

            # Calculate % Return (Engine gives totals, we just handle the ratio here)
            pnl_pct = (pnl_val / abs(initial_cost)) * 100 if initial_cost != 0 else 0

            # 2. Formatting Helpers
            color = "green" if pnl_val >= 0 else "red"
            icon = "🟢" if pnl_val >= 0 else "🔴"
            
            # 3. Header with Markdown Coloring
            # :color[text] is the Streamlit-native way to color Markdown
            expander_label = (
                f"ID: {group.id} | {ticker} | {group.strategy_name} | "
                f"{icon} **P&L: ${pnl_val:,.2f} ({pnl_pct:.2f}%)** | *{note_preview}*"
            )
            with st.expander(expander_label):
                # Display the static leg details
                history_data = []
                for l in group.legs:
                    history_data.append({
                        "Leg": f"{l.side} {l.symbol} {l.strikeprice}{l.option_type}",
                        "Entry": f"${l.entry_price:.2f}",
                        "Exit": f"${l.exit_price:.2f}",
                        "Comms": f"${(l.entry_commission)+(l.exit_commission):.2f}",
                        "P&L": f"${((l.exit_price - l.entry_price) * l.quantity * 100) if l.side == 'BTO' else ((l.entry_price - l.exit_price) * l.quantity * -100):.2f}",
                        "Closed At": format_datetime(l.exit_date)
                    })
                st.dataframe(history_data, width='stretch', hide_index=True)
                
                # Final Stats Summary
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Realized P&L", f"${stats['total_pnl']:,.2f}")
                c2.metric("Total Commissions", f"${stats['total_comm']:,.2f}")
                if group.updated_at and group.created_at:
                    # calculate the delta
                    delta = group.updated_at - group.created_at

                    # handle both days and hours for a more detailed "Empathy" for your time
                    days = delta.days
                    hours = delta.seconds // 3600

                    duration_str = f"{days}d {hours}h" if days < 7 else f"{days} Days"
                    c3.metric("Trade Duration", f"{duration_str}")
                else:
                    c3.metric("Trade Duration", "N/A")