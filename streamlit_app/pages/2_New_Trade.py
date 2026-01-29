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

import streamlit as st
import logging
import pytz
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from datetime import date, datetime, UTC
from db.models import SessionLocal, Trade, TradeGroup, Leg, Transaction
from utils.validation import validate_entry_timestamp
from utils.trades import trades_to_df, calculate_pnl, get_all_open_positions
from utils.market_clock import show_market_clock
from utils.formatters import is_valid_expiry
from utils.ui_components import render_complex_strategy_cards, render_dynamic_leg_form
from utils.logger import get_logger

# --- Initiate logging
logger = get_logger(__name__)

# Add a Test Button to the Sidebar
if st.sidebar.button("Load Test Bull Put Spread"):
    # Group Info
    st.session_state.strat_name = "Bull Put Spread"
    st.session_state.strat_date = date(2025, 12, 19)
    st.session_state.strat_time = "15:50:51"
    st.session_state.strat_note = "Bullish on CRWD"
    
    # Leg 1: Short Put (STO)
    st.session_state.l1_ticker = "CRWD"
    st.session_state.l1_exp = "20260123"
    st.session_state.l1_stk = 445.0
    st.session_state.l1_type = "Put"
    st.session_state.l1_qty = -4
    st.session_state.l1_price = 9.16
    st.session_state.l1_comm = 1.33
    
    # Leg 2: Long Put (BTO)
    st.session_state.l2_ticker = "CRWD"
    st.session_state.l2_exp = "20260123"
    st.session_state.l2_stk = 455.0
    st.session_state.l2_type = "Put"
    st.session_state.l2_qty = 4
    st.session_state.l2_price = 6.85
    st.session_state.l2_comm = 1.32
    
    st.sidebar.success("Test data loaded! Scroll to the form.")

# Add a Test Button to the Sidebar
if st.sidebar.button("Load Calendar Spread"):
    # Group Info
    st.session_state.strat_name = "Bull Put Spread"
    st.session_state.strat_date = date(2025, 12, 19)
    st.session_state.strat_time = "15:50:51"
    st.session_state.strat_note = "Bullish on CRWD"
    
    # Leg 1: Short Put (STO)
    st.session_state.l1_ticker = "CRWD"
    st.session_state.l1_exp = "20260123"
    st.session_state.l1_stk = 445.0
    st.session_state.l1_type = "Put"
    st.session_state.l1_qty = -4
    st.session_state.l1_price = 9.16

    st.session_state.l1_comm = 1.33
    
    # Leg 2: Long Put (BTO)
    st.session_state.l2_ticker = "CRWD"
    st.session_state.l2_exp = "20260123"
    st.session_state.l2_stk = 455.0
    st.session_state.l2_type = "Put"
    st.session_state.l2_qty = 4
    st.session_state.l2_price = 6.85
    st.session_state.l2_comm = 1.32
    
    st.sidebar.success("Test data loaded! Scroll to the form.")

# ---------------------------------------------------------
# 1. Cached DB fetch
# ---------------------------------------------------------
@st.cache_data(ttl=30)

# ---------------------------------------------------------
# 2. Display trades (pure UI)
# ---------------------------------------------------------
def render_trades(flat_trades, complex_groups):
    """
    Renders both flat trades and complex strategy trades
    """
    if flat_trades.empty:
        st.info("No open trades.")
        return

    # --- Section 2: Simple Trades (Flat)
    if not flat_trades.empty:
        st.header("Simple Trades")
        for t in flat_trades.itertuples(index=False):
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 1, 2])
                with c1:
                    st.write(f"Trade {t.id}:")
                    if t.strikeprice and t.expiry_dt:                        
                        type = f"**Type:** Option ({t.strategy}) {t.expiry_dt} {t.strikeprice}" 
                    else:
                        type = f"**Type:** Stock ({t.strategy})"            
                    details = f"{t.symbol} | {type}" 
                    st.write(details)
                with c2:
                    st.write(f"Units: {t.units}")
                    st.write(f"Entry: ${t.entry_price:.2f}")
                    comm = (t.entry_commissions or 0.0)
                    st.write(f"Comm: ${comm:.2f}")
                with c3:
                    st.write(f"**Notes:** {t.notes}")

    # --- Section 1: Complex Strategies (Relational) ---
    if not complex_groups.empty:
        render_complex_strategy_cards(complex_groups)
    
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

def to_occ_format(symbol, expiry, strike, option_type):
    """
    Converts inputs into a strict 21-character OCC symbol.
    Example: to_occ_format('NVDA', '20260109', 150.0, 'Call')
    """
    # 1. Root: 6 chars, right-padded
    root = f"{symbol[:6]:<6}"
    
    # 2. Expiry: YYMMDD (take last 2 digits of year)
    date_str = expiry.replace("-", "") # remove dashes if any
    yymmdd = date_str[2:] 
    
    # 3. Type: 1 char
    opt_type = "C" if option_type.upper().startswith("C") else "P"
    
    # 4. Strike: 8 chars, leading zeros (Price * 1000)
    strike_int = int(float(strike) * 1000)
    strike_str = f"{strike_int:08}"
    
    return f"{root}{yymmdd}{opt_type}{strike_str}"

# ---------------------------------------------------------
# 3. Page Header
# ---------------------------------------------------------
col1, col2 = st.columns([2, 1])
with col1:
    st.title("New Trade")
with col2:
    show_market_clock(mode="static")

# ---------------------------------------------------------
# 3a. Selection of 
# ---------------------------------------------------------
entry_mode = st.radio(
    "Select Entry Mode:",
    ["Simple (Flat)", "Complex (Relational)"],
    horizontal=True,
    help="Use Simple for single stocks/options. Use Complex for spreads and rolls."
)

st.divider()

# ---------------------------------------------------------
# 4. Initialize session defaults
# ---------------------------------------------------------
if "entry_date" not in st.session_state:
    st.session_state.entry_date = datetime.now(UTC).date()

if "entry_time" not in st.session_state:
    st.session_state.entry_time = "09:30:01"

if "entry_commission" not in st.session_state:
    st.session_state.entry_commission = 0.0

if "last_added" not in st.session_state:
    st.session_state.last_added = None

if "strat_date" not in st.session_state:
    st.session_state.strat_date = datetime.now(UTC).date()

if "strat_time" not in st.session_state:
    st.session_state.strat_time = "09:30:01"


# ---------------------------------------------------------
# 5. Conditional Form Rendering
# ---------------------------------------------------------
if entry_mode == "Simple (Flat)":
    with st.form("simple_trade_form", clear_on_submit=True):
        st.subheader("Single Leg Entry (Legacy Table)")
        
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

        col1, col2 = st.columns(2) 

        with col1:
            st.date_input("Entry date (ET)", key="entry_date")
            st.text_input("Entry time (HH:MM:SS ET)", key="entry_time")

            symbol = st.text_input("Symbol", value="SPY")
            units = st.number_input("Units (+ve buy, -ve sell)", step=1.0, value=100.0)
            notes = st.text_area("Notes", value="", placeholder="Optional notes")

        with col2:
            entry_price = st.number_input("Entry price", min_value=0.0, step=0.01, value=450.00)
            st.number_input("Entry commissions (US$)", min_value=0.0, step=0.01, key="entry_commission")

            expected_rr = st.number_input("Expected risk-reward ratio", min_value=0.0, step=0.1, value=2.0)

            strikeprice = st.number_input("Strike price (optional)", min_value=0.0)
            expiry_date = st.text_input("Expiry date (YYYYMMDD)", value="")

        # ---------------------------------------------------------
        # 6. Handle submission
        # ---------------------------------------------------------
        if st.form_submit_button("Add Simple Trade"):
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
                    asyncio.sleep(1)    # Brief pause so user sees success
                    st.rerun()  # <-- ensures fresh display
                    db.close()

            except ValueError as ve:
                st.error(f"Rule violation: {ve}")
            except Exception as e:
                st.error(f"Validation error: {e}")
else:
    st.subheader("Multi-Leg Strategy Entry")
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        eastern = pytz.timezone("US/Eastern")
        strat_date = st.date_input(
            "Entry Date", 
            key="strat_date", 
            value=st.session_state.get("strat_date", datetime.now(eastern).date())
        )
        strat_time = st.text_input(
            "Entry Time (HH:MM:SS)", 
            value=st.session_state.get("strat_time", "09:30:00"),
            key="strat_time"
        )

    with col_d2:
        strat_options = ["Calendar Spread", "Bull Put Spread", "Bear Call Spread", "Bull Bang Collar", 
                        "Iron Condor", "Custom"]
        try:
            current_strat = st.session_state.get("strat_name", "Calendar Spread")
            strat_index = strat_options.index(current_strat)
        except ValueError:
            strat_index = 0
        strat_name = st.selectbox(
            "Strategy Name",
            options=strat_options,
            index=strat_index, 
            key="strat_name"                
        )

        underlying = st.text_input("Underlying Ticker", st.session_state.get("l1_ticker", "")).upper()
        
    # Add the Global Note here
    strat_note = st.text_area(
        "Strategy Thesis / Notes",
        value=st.session_state.get("strat_note", "Playing the IV crush after earnings"),
        key="strat_note" 
    )
    
    st.markdown("---")
    
    # We will assume a 2-leg spread for the input UI
    active_legs = render_dynamic_leg_form(underlying)

    if st.button("Submit Complex Strategy", type="primary"):
        try:
            # Prepare data
            strat_dt = datetime.combine(
                st.session_state.strat_date,
                datetime.strptime(st.session_state.strat_time, "%H:%M:%S").time()
            )
            validate_entry_timestamp(strat_dt)

            with SessionLocal() as db:
                # 1. Create the Parent Group
                new_group = TradeGroup(
                    strategy_name=strat_name, 
                    status="Open",
                    notes=strat_note,
                    updated_at=strat_dt,
                    created_at=strat_dt
                )
                db.add(new_group)
                db.flush() 

                # Loop through Dynamic Legs and save
                for leg_data in active_legs:
                    # Skip legs with missing essential data
                    if not leg_data['exp'] or leg_data['stk'] == 0:
                        continue
                    
                    occ_symbol = to_occ_format(underlying, leg_data['exp'], leg_data['stk'], leg_data['type'])
                
                    new_leg = Leg(
                        group_id=new_group.id,
                        symbol=underlying,
                        side=leg_data['side'],
                        quantity=leg_data['qty'],
                        status="Active",
                        entry_date=strat_dt,
                        entry_price=leg_data['price'],
                        entry_commission=leg_data.get('comm', 0.65),
                        strikeprice=leg_data['stk'],
                        expiry_dt=leg_data['exp'],
                        option_type=leg_data['type']
                    )
                    db.add(new_leg)
                    db.flush()

                    # Create Transaction Record
                    db.add(Transaction(
                        leg_id=new_leg.id, 
                        action=leg_data['side'], 
                        quantity=leg_data['qty'], 
                        price=leg_data['price'], 
                        commission=leg_data.get('comm', 0.65), 
                        timestamp=strat_dt
                    ))

                db.commit()

            message = f"Successfully opened {strat_name} for {underlying}!" 
            st.toast({message})
            logger.info(f"[New_Trade] {message}")
            
            # Reset the dynamic legs for the next entry
            if "dynamic_legs" in st.session_state:
                del st.session_state.dynamic_legs
            st.rerun()
        except Exception as e:
            st.error(f"Error saving complex trade: {e}")
            logger.info(f"[New_Trade] Error Saving complex trade {strat_name} for {underlying}: {e}")
   
# ---------------------------------------------------------
# 7. Display updated trades
# ---------------------------------------------------------
#st.header("Open Trades")
#flat_trades, complex_groups = get_all_open_positions()
#render_trades(flat_trades, complex_groups)