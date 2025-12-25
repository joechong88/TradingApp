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
from utils.formatters import is_valid_expiry

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
# 2. Enhanced Validation Logic
# ---------------------------------------------------------
def validate_strategy_units(strategy, units):
    """
    Validates units based on the selected strategy.
    Requires strike/expiry for option-related strategies
    Raises ValueError if criteria not met.
    """
    strat = strategy.lower()
    option_strategies = ["csp", "cc", "long option", "short option"]
    
    # 1. Check for Options Metadata
    if strat in option_strategies:
        if strikeprice <= 0:
            raise ValueError(f"Strategy '{strategy}' requires a valid Strike Price")
        if not expiry or len(expiry.strip()) < 8:
            raise ValueError(f"Strategy '{strategy}' requires an Expiry Date (YYYYMMDD)")
    if strat == "long" and units <= 0:
        raise ValueError("Long Stock strategy requires positive units (buying shares).")
    
    if strat == "short" and units >= 0:
        raise ValueError("Short Stock strategy requires negative units (shorting shares).")
    
    if strat in ["csp", "cc"] and units > -1:
        raise ValueError(f"{strategy} involves selling/writing contracts. Units must be -1 or less.")
    
    if strat == "long option" and units < 1:
        raise ValueError("Long Option (Buying Calls/Puts) requires at least 1 unit.")
        
    if strat == "short option" and units < 1:
        # Based on your requirement: "short option units should be minimal 1 and above"
        raise ValueError("Short Option requires at least 1 unit.")

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

# --- Strategy Selection (outside form for reactivity) ---
strategy = st.selectbox(
    "Strategy", 
    ["Long", "Short", "CSP", "CC", "Long Option", "Short Option"],
    key="strat_selector"
)

# --- Dynamic Unit Defaults ---
strat_lower = strategy.lower()
if strat_lower in ["long", "short"]:
    default_units = 100.0
elif strat_lower in ["csp", "cc"]:
    default_units = -1.0
else:
    default_units = 1.0

# ---------------------------------------------------------
# 5. Form (isolated)
# ---------------------------------------------------------
with st.form("new_trade_form", clear_on_submit=False):
    st.date_input("Entry date (ET)", key="entry_date")
    st.text_input("Entry time (HH:MM:SS ET)", key="entry_time")

    symbol = st.text_input("Symbol", value="SPY")
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
            # 1. Date/Time Validation
            entry_dt = datetime.combine(
                st.session_state.entry_date,
                datetime.strptime(st.session_state.entry_time, "%H:%M:%S").time()
            )
            validate_entry_timestamp(entry_dt)

            # 2. Option-Specific Validation
            is_option = strat_lower in ["csp", "cc", "long option", "short option"]
            
            if is_option:
                if strikeprice <= 0:
                    raise ValueError("Strike Price is required for options.")
                
                # Clean the input
                expiry_clean = expiry_date.strip()
                
                # REGEX VALIDATION
                if not is_valid_expiry(expiry_clean):
                    raise ValueError("Expiry must be 8 digits in YYYYMMDD format (e.g., 20251219).")
            
            # 3. Strategy-specific Unit Validation
            if strat_lower == "long" and units <= 0:
                raise ValueError("Long strategy requires positive units.")
            if strat_lower == "short" and units >= 0:
                raise ValueError("Short strategy requires negative units.")
            if strat_lower in ["csp", "cc"] and units > -1:
                raise ValueError(f"{strategy} requires units of -1 or less.") 
            if strat_lower in ["long option", "short option"] and units < 1:
                raise ValueError(f"{strategy} requires units of 1 or more.")

            with SessionLocal() as db:
                trade = Trade(
                    symbol=symbol.upper().strip(),
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

                # Store info for confirmation message before rerun
                st.session_state.last_added = f"{strategy} {symbol} at {entry_price}"
            
            st.success(f"✅ Trade Confirmed: {st.session_state.last_added}")
            st.ballons()    # Visual confirmation
            asyncio.sleep(1)    # Brief pause so user sees success
            st.rerun()  # <-- ensures fresh display

        except ValueError as ve:
            st.error(f"Rule violation: {ve}")
        except Exception as e:
            st.error(f"Validation error: {e}")
   
# ---------------------------------------------------------
# 7. Display updated trades
# ---------------------------------------------------------
st.header("Open Trades")
render_trades(load_open_trades())