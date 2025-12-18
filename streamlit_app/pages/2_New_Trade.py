import asyncio

# Ensure an event loop exists before anything else
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import streamlit as st
import logging
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, UTC
from db.models import SessionLocal, Trade
from utils.validation import validate_entry_timestamp
from utils.trades import trades_to_df, calculate_pnl
from utils.market_clock import show_market_clock

# ---------------------------------------------------------
# 1. Cached DB fetch
# ---------------------------------------------------------
@st.cache_data(ttl=30)
def load_open_trades():
    with SessionLocal() as db:
        return (
            db.query(Trade)
            .filter(Trade.is_open == True)
            .order_by(desc(Trade.entry_dt))
            .all()
        )

# ---------------------------------------------------------
# 2. Display trades (pure UI)
# ---------------------------------------------------------
def render_trades(trades):
    if not trades:
        st.info("No open trades.")
        return

    for t in trades:
        st.subheader(f"Trade {t.id}: {t.symbol}")

        if t.strikeprice and t.expiry_dt:
            st.write(f"**Type:** Option ({t.strategy})")
            st.write(f"**Strike:** {t.strikeprice}")
            st.write(f"**Expiry:** {t.expiry_dt}")
        else:
            st.write(f"**Type:** Stock ({t.strategy})")

        st.write(f"**Units:** {t.units}")
        st.write(f"**Entry Price:** {t.entry_price}")

        if t.notes:
            st.write(f"**Notes:** {t.notes}")

# ---------------------------------------------------------
# 3. Page Header
# ---------------------------------------------------------
col1, col2 = st.columns([2, 1])
with col1:
    st.title("New Trade")
with col2:
    show_market_clock(mode="static")

# ---------------------------------------------------------
# 4. Initialize session defaults
# ---------------------------------------------------------
if "entry_date" not in st.session_state:
    st.session_state.entry_date = datetime.now(UTC).date()

if "entry_time" not in st.session_state:
    st.session_state.entry_time = "09:30:01"

if "entry_commission" not in st.session_state:
    st.session_state.entry_commission = 0.0

# ---------------------------------------------------------
# 5. Form (isolated)
# ---------------------------------------------------------
with st.form("new_trade_form", clear_on_submit=False):
    st.date_input("Entry date (ET)", key="entry_date")
    st.text_input("Entry time (HH:MM:SS ET)", key="entry_time")

    symbol = st.text_input("Symbol", value="SPY")
    strategy = st.selectbox("Strategy", ["Long", "Short", "CSP", "CC", "Long Option", "Short Option"])
    units = st.number_input("Units (+ve buy, -ve sell)", step=1.0, value=100.0)
    entry_price = st.number_input("Entry price", min_value=0.0, step=0.01, value=450.00)
    st.number_input("Entry commissions (US$)", min_value=0.0, step=0.01, key="entry_commission")

    expected_rr = st.number_input("Expected risk-reward ratio", min_value=0.0, step=0.1, value=2.0)

    strikeprice = st.number_input("Strike price (optional)", min_value=0.0)
    expiry_date = st.text_input("Expiry date (YYYYMMDD)", value="")

    notes = st.text_area("Notes", value="", placeholder="Optional notes")

    submitted = st.form_submit_button("Add trade")

    # ---------------------------------------------------------
    # 6. Handle submission
    # ---------------------------------------------------------
    if submitted:
        try:
            entry_dt = datetime.combine(
                st.session_state.entry_date,
                datetime.strptime(st.session_state.entry_time, "%H:%M:%S").time()
            )

            validate_entry_timestamp(entry_dt)

            with SessionLocal() as db:
                trade = Trade(
                    symbol=symbol,
                    strategy=strategy,
                    units=units,
                    strikeprice=strikeprice if strikeprice > 0 else None,
                    expiry_dt=expiry_date or None,
                    entry_price=entry_price,
                    expected_rr=expected_rr,
                    entry_dt=entry_dt,
                    entry_commissions=st.session_state.entry_commission,
                    is_open=True,
                    notes=notes
                )
                db.add(trade)
                db.commit()

            st.success("Trade added.")
            st.rerun()  # <-- ensures fresh display

        except Exception as e:
            st.error(f"Validation error: {e}")
   
# ---------------------------------------------------------
# 7. Display updated trades
# ---------------------------------------------------------
st.header("Open Trades")
render_trades(load_open_trades())