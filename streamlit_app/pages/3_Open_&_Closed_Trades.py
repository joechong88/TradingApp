import asyncio

# Ensure an event loop exists before anything else
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import streamlit as st
import pandas as pd
from datetime import datetime, UTC
from sqlalchemy.orm import Session
from db.models import SessionLocal, Trade
from ibkr.data import get_live_quote

st.title("Open & Closed trades")

if "exit_date" not in st.session_state:
    st.session_state.exit_date = datetime.now(UTC).date()
if "exit_time" not in st.session_state:
    st.session_state.exit_time = "16:00:00"

def fetch_trades():
    with SessionLocal() as db:  # type: Session
        trades = db.query(Trade).order_by(Trade.id.desc()).all()
        return trades

def to_df(trades):
    return pd.DataFrame([{
        "id": t.id,
        "symbol": t.symbol,
        "strategy": t.strategy,
        "units": t.units,
        "entry_price": t.entry_price,
        "entry_commissions": t.entry_commissions,
        "strikeprice": t.strikeprice,
        "expiry_dt": t.expiry_dt,
        "expected_rr": t.expected_rr,
        "entry_dt": t.entry_dt,
        "is_open": t.is_open,
        "exit_price": t.exit_price,
        "exit_dt": t.exit_dt,
        "exit_commissions": t.exit_commissions,
        "notes": t.notes
    } for t in trades])

trades = fetch_trades()
df = to_df(trades)

open_df = df[df["is_open"] == True].copy()
closed_df = df[df["is_open"] == False].copy()

st.subheader("Open trades")
if open_df.empty:
    st.info("No open trades.")
else:
    # Live quotes per symbol
    symbols = open_df["symbol"].unique().tolist()
    quotes = {s: get_live_quote(s) for s in symbols}
    open_df["live_last"] = open_df["symbol"].map(lambda s: quotes[s]["last"])
    open_df["live_bid"] = open_df["symbol"].map(lambda s: quotes[s]["bid"])
    open_df["live_ask"] = open_df["symbol"].map(lambda s: quotes[s]["ask"])

    # calculate P&L per trade
    open_df["P&L"] = (
        (open_df["live_last"] - open_df["entry_price"]) * open_df["units"] - open_df["entry_commissions"].fillna(0.0)
    )

    # Re-order columns: show Live Price and PnL earlier
    cols_order = ["symbol", "live_last", "P&L"] + [
                  c for c in open_df.columns if c not in ["symbol", "live_last", "P&L"]
                ]
    open_df = open_df[cols_order]
    
    st.dataframe(open_df, use_container_width=True)

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

st.divider()
st.subheader("Closed trades")
st.dataframe(closed_df, use_container_width=True)