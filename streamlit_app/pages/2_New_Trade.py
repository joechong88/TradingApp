import asyncio

# Ensure an event loop exists before anything else
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import streamlit as st
from sqlalchemy.orm import Session
from datetime import datetime, UTC
from db.models import SessionLocal, Trade
from utils.validation import validate_entry_timestamp

st.title("New trade")

# --- Initialize session_state defaults once ---
default_date = datetime.now(UTC).date()
if "entry_date" not in st.session_state:
    st.session_state.entry_date = default_date
if "entry_time" not in st.session_state:
    st.session_state.entry_time = "09:30:01"   # default string
if "entry_commission" not in st.session_state:
    st.session_state.entry_commission = 0.0     # default commission
if "exit_commission" not in st.session_state:
    st.session_state.exit_commission = 0.0      # default commission

with st.form("new_trade_form", clear_on_submit=False):
    st.date_input("Entry date (ET assumed)", key="entry_date")
    st.text_input("Entry time (HH:MM:SS) (ET assumed)", key="entry_time")
    symbol = st.text_input("Symbol", value="SPY")
    strategy = st.selectbox("Strategy", ["Long", "Short", "Call", "Put"])
    units = st.number_input("Units", min_value=0.0, step=1.0, value=100.0)
    entry_price = st.number_input("Entry price", min_value=0.0, step=0.01, value=450.00)
    st.number_input("Emtry commissions (US$)", min_value=0.0, step=0.01, value=1.00, key="entry_commission")
    expected_rr = st.number_input("Expected risk-reward ratio", min_value=0.0, step=0.1, value=2.0)
    notes = st.text_area("Notes", value="", placeholder="Optional notes")

    submitted = st.form_submit_button("Add trade")
    if submitted:
        try:
            entry_dt = datetime.combine(
                        st.session_state.entry_date,
                        datetime.strptime(st.session_state.entry_time, "%H:%M:%S").time()
                    )
            _ = validate_entry_timestamp(entry_dt)
            commission = st.session_state.entry_commission

            # Store in UTC for consistency
            with SessionLocal() as db:  # type: Session
                trade = Trade(
                    symbol=symbol,
                    strategy=strategy,
                    units=units,
                    entry_price=entry_price,
                    expected_rr=expected_rr,
                    entry_dt=entry_dt,  # assume UTC input; Streamlit returns naive -> treat as UTC
                    entry_commissions=commission,
                    is_open=True,
                    notes=notes
                )
                db.add(trade)
                db.commit()
            st.success("Trade added.")
        except Exception as e:
            st.error(f"Validation error: {e}")