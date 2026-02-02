import streamlit as st
import pandas as pd
import pytz
import time

from datetime import datetime
from utils.formatters import format_datetime, safe_markdown
from utils.config_loader import load_config
from utils.trades import calculate_strategy_cost, execute_roll_short_call, get_group_realized_pnl, calculate_comprehensive_pnl, execute_close_strategy, get_active_legs_by_group

# Load global variable
config = load_config()
OPTIONS_COMMISSION = config.get("fees", {}).get("option_commission", 0.65)

# --- Function to display the top header dashboard metrics for Open Trades
# --- 
def render_top_metrics(total_open_pnl, stk_pnl, stk_count, opt_pnl, opt_count):
    """
    Renders a compact, custom-styled HTML dashboard for trading metrics.
    """
    # Define color logic
    def get_color_class(val):
        return "positive" if val >= 0 else "negative"

    tot_color = get_color_class(total_open_pnl)
    stk_color = get_color_class(stk_pnl)
    opt_color = get_color_class(opt_pnl)

    # --- Custom CSS for the Mini Dashboard ---
    st.markdown("""
    <style>
        .metric-container {
            display: flex;
            justify-content: space-between;
            padding: 12px;
            background-color: #f8f9fa;
            border-radius: 8px;
            border: 1px solid #e9ecef;
            margin-bottom: 15px;
        }
        .metric-card {
            text-align: center;
            flex: 1;
        }
        .metric-label {
            font-size: 0.75rem;
            color: #6c757d;
            margin-bottom: 2px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .metric-value {
            font-size: 1.25rem;
            font-weight: 700;
        }
        .metric-delta {
            font-size: 0.75rem;
            color: #6c757d;
            margin-top: 1px;
        }
        .positive { color: #28a745 !important; }
        .negative { color: #dc3545 !important; }
    </style>
    """, unsafe_allow_html=True)

    # --- Render the Dashboard ---
    st.markdown(f"""
    <div class="metric-container">
        <div class="metric-card">
            <div class="metric-label">Total Open P&L</div>
            <div class="metric-value {tot_color}">${total_open_pnl:,.2f}</div>
        </div>
        <div class="metric-card" style="border-left: 1px solid #dee2e6; border-right: 1px solid #dee2e6;">
            <div class="metric-label">Stocks P&L</div>
            <div class="metric-value {stk_color}">${stk_pnl:,.2f}</div>
            <div class="metric-delta">{stk_count} Positions</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Options P&L</div>
            <div class="metric-value {opt_color}">${opt_pnl:,.2f}</div>
            <div class="metric-delta">{opt_count} Positions</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

@st.fragment
def render_complex_strategy_cards(complex_groups):
    """
    Reusable UI component to display complex option strategies in a row-based format.
    """
    if complex_groups.empty:
        st.info("No open complex strategies found.")
        return

    st.header("Complex Options Strategies")
    
    for group in complex_groups.itertuples(index=False):
        # Temporary debug inside the loop
        all_legs = list(group.legs)
        
        # 1. Data Preparation
        note_preview_extract = group.notes[:30] if group.notes else "No notes"
        note_preview = safe_markdown(note_preview_extract)  # Require to avoid Math Mode with Streamlit.
        ticker = group.legs[0].symbol[:6].strip() if group.legs else "Data Error"
        # --- SEPARATE LEGS BY STATUS ---
        active_legs = [l for l in all_legs if str(l.status).strip().lower() == 'active']
        history_legs = [l for l in all_legs if str(l.status).strip().lower() in ['rolled', 'closed']]
        # Debug print (Optional: Remove after testing)
        #st.write(f"Group {group.group_id}: Found {len(active_legs)} active, {len(history_legs)} history")

        # 1a. Prepare the data for the P&L engine
        strategy_pnl = None

        active_prices = []
        for l in group.legs:
            if getattr(l, 'live_price', None) is not None:
                active_prices.append({'leg_id': l.id, 'live_price': l.live_price})

        # --- CALL THE COMPREHENSIVE P&L ENGINE ---
        pnl_data = calculate_comprehensive_pnl(group.group_id, active_legs_data=active_prices)
        
        initial_cost = pnl_data["initial_debit"]
        label = "Initial Net Credit" if initial_cost > 0 else "Initial Net Debit"
        help = "The total net debit paid to open the original strategy" if initial_cost > 0 else "Full Net Credit received to open the original strategy"
        current_pnl = pnl_data["total_pnl"]
        # P&L Percent is now calculated against the Initial Debit
        pnl_pct = (current_pnl / abs(initial_cost)) * 100 if initial_cost != 0 else 0

        pnl_color = "🟢" if current_pnl >= 0 else "🔴"
        pnl_str = f"${current_pnl:,.2f} ({pnl_pct:.2f}%)"
        
        # 2. Expander Header
        expander_label = (
            f"Group ID: {group.group_id} | "
            f"{ticker} | {group.strategy} | "
            f"{pnl_color} {pnl_str} | "
            f"*{note_preview}*"
        )
        with st.expander(expander_label, expanded=False):
            st.write(f"**Trade Thesis:** {group.notes if group.notes else 'N/A'}")

            # --- SECTION A: ACTIVE LEGS ---
            st.markdown("### 🎯 Active Legs")

            active_data = []

            for l in active_legs:
                # 1. NEW: Individual Leg P&L Calculation for Active Legs
                leg_pnl = 0.0
                if getattr(l, 'live_price', None) is not None:
                    # Long positions (BTO/BUY) profit when Mark > Entry
                    if l.side.upper() in ['BTO', 'BUY', 'LONG']:
                        leg_pnl = (l.live_price - l.entry_price) * l.quantity * 100
                    # Short positions (STO/SELL) profit when Entry > Mark
                    else: 
                        leg_pnl = (l.entry_price - l.live_price) * abs(l.quantity) * 100
                
                # 2. Build the dictionary with the new P&L column
                active_data.append({
                    "Details": f"{l.expiry_dt} {l.strikeprice} {l.option_type}",
                    "Action": l.side,
                    "Qty": l.quantity,
                    "Entry": f"${l.entry_price:.2f}",
                    "Mark": f"${l.live_price:.2f}" if getattr(l, 'live_price', None) else "N/A",
                    "Comm": f"${l.entry_commission:.2f}",
                    "P&L": f"${leg_pnl:,.2f}" if getattr(l, 'live_price', None) else "N/A" # <-- ADDED THIS
                })
            
            st.table(active_data)

            # --- SECTION B: TRADE HISTORY (ROLLED LEGS) ---
            if history_legs:
                st.markdown("### 📜 Trade History (Rolled)")
                history_data = []
                total_history_pnl = 0.0
                total_history_comms = 0.0
                for l in history_legs:
                    # Logic for individual leg P&L calculation
                    leg_pnl = (l.exit_price - l.entry_price) * l.quantity * 100 if l.side in ['BTO', 'BUY'] \
                              else (l.entry_price - l.exit_price) * abs(l.quantity) * 100
                    leg_comms = (l.entry_commission or 0) + (l.exit_commission or 0)

                    total_history_pnl += leg_pnl
                    total_history_comms += leg_comms
                    
                    history_data.append({
                        "Leg": f"{l.side} {l.expiry_dt} {l.strikeprice}{l.option_type}",
                        "Entry": f"${l.entry_price:.2f}",
                        "Exit": f"${l.exit_price:.2f}",
                        "P&L": f"${leg_pnl:,.2f}",
                        "Comms": f"${(l.entry_commission)+(l.exit_commission):.2f}",
                        "Closed At": format_datetime(l.exit_date) if l.exit_date else "N/A"
                    })
                st.table(history_data)

                # --- NEW: Realized Summary Row ---
                col_empty, col_res_pnl, col_res_comm = st.columns([2.5, 1, 1])
    
                with col_res_pnl:
                    st.write("**Total Realized P&L**")
                    pnl_color = "green" if total_history_pnl >= 0 else "red"
                    st.markdown(f":{pnl_color}[**${total_history_pnl:,.2f}**]")

                with col_res_comm:
                    st.write("**Total Comms**")
                    st.write(f"**${total_history_comms:,.2f}**")

            st.divider()

            # 4. Action & Metric Row
            col_basis, col_pnl, col_btn1, col_btn2 = st.columns([1.5, 1.5, 1, 1])

            with col_basis:
                st.metric(
                    label=label, 
                    value=f"${abs(initial_cost):,.2f}", 
                    help=help
                )

            with col_pnl:
                if current_pnl is not None:
                    st.metric(
                        label="Strategy P&L",
                        value=f"${current_pnl:,.2f}",
                        delta=f"{pnl_pct:.2f}%",
                        help="Total P&L including all rolled credits and current open value."
                    )
                else:
                    st.info("Live quotes pending...")     

            with col_btn1:
                # Buttons use the group.id to ensure unique keys
                # 1. Identify the Short Call (Side is 'Sell', and it's a Call 'C')
                # Assuming your leg objects have .side and .option_type attributes
                short_call_legs = [
                    l for l in group.legs 
                    if l.side.upper() in ["SELL", "STO"] and l.option_type.upper() in ["C", "CALL"]
                ]

                if st.button("Roll Short Leg", key=f"roll_{group.group_id}", width='stretch'):
                    if not short_call_legs:
                        st.error("No active short call found in this group.")
                    else:
                        # 2. Call the dialog function
                        # This opens the modal and passes the specific leg data
                        roll_short_call_dialog(group.group_id, short_call_legs[0])
            
            with col_btn2:
                # 1. Create a key for this specific group's dialog state
                dialog_key = f"active_dialog_{group.group_id}"

                # 2. Trigger the dialog if the button is clicked OR if a review is already in progress
                if st.button("Close Strategy", key=f"close_btn_{group.group_id}", width='stretch'):
                    st.session_state[f"active_dialog_{group.group_id}"] = True
                    # Set initial states onlu if they don't exist
                    if f"summary_view_{group.group_id}" not in st.session_state:
                        est_tz = pytz.timezone('America/New_York')
                        now_est = datetime.now(est_tz)
                        st.session_state[f"close_date_{group.group_id}"] = now_est.date()
                        st.session_state[f"close_time_{group.group_id}"] = now_est.strftime("%H:%M:%S")
                        st.session_state[f"summary_view_{group.group_id}"] = False
                    st.rerun()
                
                # Check if the dialog should be open (this survives the rerun)
                if st.session_state.get(f"active_dialog_{group.group_id}"):
                    # 4. Prepare the live price data for the Summary calculation
                    active_prices = [
                        {'leg_id': l.id, 'live_price': getattr(l, 'live_price', 0.0)} 
                        for l in group.legs
                    ]
                
                    # 5. Call the dialog function
                    close_strategy_dialog(group.group_id, active_prices)

def get_styled_trade_df(df: pd.DataFrame, is_open: bool = True):
    """
    Presentation Logic: Handles column ordering, renaming, 
    styling, and Streamlit column configurations.
    """
    from utils.formatters import pnl_color

    if df.empty:
        return None, {}

    # 1. Define Column Order based on trade state
    if is_open:
        # Columns specific to the Open Trades view
        desired_order = [
            "id", "trade_desc", "pnl", "pnl_pct", "itm_status", "days_to_expiry", 
            "option_last", "stock_last", "live_price",  
            "entry_price", "units", "entry_commissions", "entry_dt"
        ]
    else:
        # Columns specific to the CLosed Trades view
        desired_order = [
            "id", "trade_desc", "units", "pnl", "pnl_pct", "entry_price", 
            "exit_price", "entry_commissions", "exit_commissions", 
            "entry_dt", "exit_dt", "duration"
        ]
    
    desired_order += ["notes"]
    
    # Filter only columns that actually exist in the dataframe
    display_cols = [c for c in desired_order if c in df.columns]
    df_view = df[display_cols].copy()

    # Sort Logic
    if not is_open and "exit_dt" in df_view.columns:
        df_view = df_view.sort_values("exit_dt", ascending=False)
    elif is_open and "days_to_expiry" in df_view.columns:
        df_view = df_view.sort_values("days_to_expiry", ascending=True)

    # 2. Define Streamlit Column Configs (Labels and Formats)
    column_config = {
        "trade_desc": st.column_config.TextColumn("Trade Details", width="medium"),
        "itm_status": "ITM/OTM",
        "units": st.column_config.NumberColumn("Units", format="%.2f"),
        "pnl": st.column_config.NumberColumn("P&L", format="$%.2f"),
        "pnl_pct": st.column_config.NumberColumn("P&L %", format="%d%%"),
        "days_to_expiry": st.column_config.NumberColumn("Days to Expiry", format="%d"),
        "stock_last": st.column_config.NumberColumn("Stock Price (Last)", format="$%.2f"),
        "live_price": st.column_config.NumberColumn("Live Price", format="$%.2f"),
        "entry_price": st.column_config.NumberColumn("Entry Price", format="$%.2f"),
        "entry_commissions": st.column_config.NumberColumn("Entry Comm", format="$%.2f"),
        "exit_price": st.column_config.NumberColumn("Exit Price", format="$%.2f"),
        "exit_commissions": st.column_config.NumberColumn("Exit Comm", format="$%.2f"),
        "entry_dt": "Entry Date/Time",
        "exit_dt": "Exit Date/Time",
        "duration": "Duration",
        "notes": "Notes"
    }

    # 3. Apply Pandas Styling (Colors and Gradients)
    from utils.formatters import pnl_color, expiry_color
    styled = df_view.style.format({
        "entry_price": "${:,.2f}",
        "entry_commissions": "${:,.2f}",
        "exit_price": "${:,.2f}",
        "exit_commissions": "${:,.2f}",
        "pnl": "${:,.2f}",
        "pnl_pct": "{:.0f}%",
        "option_last": "${:,.2f}",
        "stock_last": "${:,.2f}",
        "live_price": "${:,.2f}"
    }, na_rep="$0.00")
    
    # apply text alignment
    numeric_cols = [c for c in ["pnl", "pnl_pct", "entry_price", "exit_price", "option_last", "stock_last", "live_price"] if c in df_view.columns]
    styled = styled.set_properties(subset=numeric_cols, **{"text-align": "right"})

    # apply conditional coloring
    if "pnl" in df_view.columns:
        styled = styled.map(pnl_color, subset="pnl")
    
    if "days_to_expiry" in df_view.columns:
        styled = styled.map(expiry_color, subset="days_to_expiry")
    
    # apply the P&L % gradient
    if "pnl_pct" in df_view.columns:
        styled = styled.background_gradient(
            subset=["pnl_pct"],
            cmap="RdYlGn",
            vmin=0, 
            vmax=80
        )

    return styled, column_config

import streamlit as st
from datetime import datetime
from db.models import SessionLocal, Trade

@st.fragment
def render_close_trade_form(open_df):
    """
    Renders the UI form to close an open trade.
    Expects a DataFrame that includes 'id', 'trade_desc', and 'days_to_expiry'.
    """
    st.subheader("Close an open trade")

    if open_df.empty:
        st.info("No open trades to close.")
        return

    # --- 1. Align sorting with the Table ---
    # We sort by days_to_expiry (ascending) to match the UI table
    sort_df = open_df.sort_values("days_to_expiry", ascending=True).copy()
    
    sort_df["display_name"] = sort_df["id"].astype(str) + " | " + sort_df["trade_desc"]
    trade_map = dict(zip(sort_df["display_name"], sort_df["id"]))

    # --- 1a. Calculate Eastern Time Defaults ---
    tz_et = pytz.timezone('US/Eastern')
    now_et = datetime.now(tz_et)
    current_date_et = now_et.date()
    current_time_et = now_et.strftime("%H:%M:%S")

    # --- 1b. Initialize Session State values if they don't exist
    # This prevents the "value set via Session State API" warning
    if "exit_date" not in st.session_state:
        st.session_state.exit_date = current_date_et
    if "exit_time" not in st.session_state:
        st.session_state.exit_time = current_time_et
    
    # --- 2. Render Form Inputs ---
    sel_label = st.selectbox("Select trade ID to close", list(trade_map.keys()))
    #sel_id = trade_map[sel_label]

    # --- 2a. Check that the selected id is valid, to prevent Key Error
    if sel_label not in sort_df["display_name"].values:
        st.stop()
    
    selected_row = sort_df[sort_df["display_name"] == sel_label].iloc[0]
    default_exit_price = float(selected_row["entry_price"])
    default_exit_comm = float(selected_row["entry_commissions"])
    sel_id = int(selected_row["id"]) 
    
    col1, col2 = st.columns(2)
    with col1:
        st.date_input("Exit date (ET assumed)", key="exit_date")
        st.text_input("Exit time (HH:MM:SS) (ET assumed)", key="exit_time")
    with col2:
        exit_price = st.number_input("Exit price", min_value=0.0, step=0.01, value=default_exit_price)
        exit_commissions = st.number_input("Exit Commissions", min_value=0.0, step=0.01, value=default_exit_comm)

    # --- 3. Process Closing ---
    if st.button("Close trade", width='stretch'):
        try:
            # Parse the time string
            time_obj = datetime.strptime(st.session_state.exit_time, "%H:%M:%S").time()
            exit_dt = datetime.combine(st.session_state.exit_date, time_obj)
            
            with SessionLocal() as db:
                t = db.query(Trade).filter(Trade.id == sel_id).first()
                if not t:
                    st.error("Trade not found in database.")
                else:
                    t.exit_price = exit_price
                    t.exit_dt = exit_dt
                    t.exit_commissions = exit_commissions
                    t.is_open = False
                    db.commit()
                    message = f"Trade {sel_id} closed successfully!"
                    show_trade_confirmation(
                        message=message,
                        success_type="toast"
                    ) 

                    st.rerun() # Refresh to update the table
        except ValueError:
            st.error("Invalid time format. Please use HH:MM:SS.")

@st.dialog("Roll Short Call")
def roll_short_call_dialog(group_id, leg):
    import logging
    from utils.logger import get_logger

    # --- Initiate logging
    logger = get_logger(__name__)

    # Namespace the keys with group_id so different strategies don't conflict
    time_key = f"roll_time_{group_id}"
    date_key = f"roll_date_{group_id}"
    
    # Set default to current EST time, and ONLY generate the initial time if it's not already stored
    est_tz = pytz.timezone('America/New_York')
    now_est = datetime.now(est_tz)

    if time_key not in st.session_state:
        st.session_state[time_key] = now_est.strftime("%H:%M:%S")
    if date_key not in st.session_state:
        st.session_state[date_key] = now_est.date()

    st.write(f"Rolling **{leg.symbol}** | Current: {leg.expiry_dt} @ {leg.strikeprice}")

    # 2. Field to collect/confirm the execution time
    col_d, col_t = st.columns(2)
    with col_d:
        # Defaults to today's date in EST
        trade_date = st.date_input("Execution Date (EST)", value=st.session_state[date_key])
    with col_t:
        # Defaults to current minute in EST
        current_time_str = now_est.strftime("%H:%M:%S")
        trade_time_str = st.text_input("Execution Time (EST) - HH:MM:SS", value=st.session_state[time_key])
    
    # Combine into a single timezone-aware datetime object
    try:
        trade_time_obj = datetime.strptime(trade_time_str, "%H:%M:%S").time()
        execution_dt = est_tz.localize(datetime.combine(trade_date, trade_time_obj))
    except ValueError:
        st.error("Invalid time format! Please use HH:MM:SS (e.g., 14:30:05)")
        st.stop()

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Close Existing")
        exit_p = st.number_input("BTC Price", value=float(leg.live_price or 0.0))
        exit_c = st.number_input("BTC Comm", value=OPTIONS_COMMISSION)
        
    with col2:
        st.subheader("Open New")
        new_exp = st.text_input("New Expiry (YYYYMMDD)", value=leg.expiry_dt)
        new_strike = st.number_input("New Strike", value=float(leg.strikeprice))
        new_entry_p = st.number_input("STO Price (Credit)", value=0.0)
        new_entry_c = st.number_input("STO Comm", value=OPTIONS_COMMISSION)

    if st.button("Execute Roll"):
        logger.debug(f"[roll_short_call_dialog] Button clicked!")
        params = {
            "expiry_dt": new_exp,
            "strikeprice": new_strike,
            "entry_price": new_entry_p,
            "entry_comm": new_entry_c,
            "execution_dt": execution_dt
        }
        logger.debug(f"[roll_short_call_dialog] Calling execute_roll_short_call with {params}")

        success, msg = execute_roll_short_call(group_id, leg.id, exit_p, exit_c, params)
        if success:
            # clear the session state for this group so it's fresh for the next roll
            del st.session_state[time_key]
            del st.session_state[date_key]

            message = f"Roll documented."
            show_trade_confirmation(
                message=message,
                success_type="toast"
            )

            logger.debug(f"[roll_short_call_dialog] Executed rolling successfully")
            st.rerun()
        else:
            logger.debug(f"[roll_short_call_dialog] Failed execute_roll_short_call with {msg}")
            st.error(f"Failed: {msg}")

@st.dialog("Close Strategy")
def close_strategy_dialog(group_id, active_prices):
    # Initiate logging
    import logging
    from utils.logger import get_logger
    logger = get_logger(__name__)
    # DEBUG: See what view we are in
    logger.info(f"Current View State: {st.session_state.get(f'summary_view_{group_id}')}")

    est_tz = pytz.timezone('America/New_York')

    # View A: THE SUMMARY (Only shows after 'Review' is clicked)
    if st.session_state[f"summary_view_{group_id}"]:
        logger.debug(f"[close_strategy_dialog] Entering View A Summary")
        results = st.session_state[f"final_results_{group_id}"]
        st.subheader("📊 Final Trade Summary")
        
        col1, col2 = st.columns(2)
        col1.metric("Initial Basis", f"${results['initial_debit']:,.2f}")
        
        color = "green" if results['total_pnl'] >= 0 else "red"
        col2.metric("Total Realized P&L", f"${results['total_pnl']:,.2f}", 
                  delta=f"{results['pnl_pct']:.2f}%")
        
        st.write("---")
        st.write("**Final Exit Leg Details:**")
        for leg_id, d in st.session_state[f"pending_exit_{group_id}"].items():
            #leg_str = f"{leg.strikeprice}{leg.option_type} ({leg.side})"
            st.caption(f"Leg {leg_id}: Price ${d['price']:.2f} | Comm ${d['commission']:.2f}")

        if st.button("Finalize & Save", type="primary", width='stretch'):
            success = execute_close_strategy(
                group_id, 
                st.session_state[f"pending_exit_{group_id}"],
                st.session_state[f"execution_dt_{group_id}"]
            )
            if success:
                # Cleanup session state for this group
                for key in [f"summary_view_{group_id}", f"active_dialog_{group_id}", f"final_results_{group_id}", 
                            f"pending_exit_{group_id}", f"close_time_{group_id}", f"active_dialog_{group_id}"]:
                    if key in st.session_state: del st.session_state[key]
                st.rerun() # This rerun is safe now because we are done with the dialog
        
        if st.button("Back to Edit", width='stretch'):
            st.session_state[f"summary_view_{group_id}"] = False
            st.rerun()
        return  # Stop execution here so VIEW B doesn't render

    # VIEW B: THE INPUT FORM
    st.write(f"### Closing Group {group_id}")
    st.info("Enter the final exit prices for all active legs.")
    logger.debug(f"[close_strategy_dialog] Entering View B Input Form")

    # 1. Date and Time Selection
    col_d, col_t = st.columns(2)
    with col_d:
        trade_date = st.date_input("Exit Date (EST)", key=f"close_date_{group_id}")
    with col_t:
        trade_time_str = st.text_input("Exit Time (EST)", key=f"close_time_{group_id}")

    st.divider()

     # CALL THE SEPARATE FUNCTION INSTEAD OF DB QUERY
    active_legs = get_active_legs_by_group(group_id)

    # Dictionary to store user input
    exit_details = {}

    for i, leg in enumerate(active_legs):
        # 1. Check if we have previously entered data in session_state
        pending_data = st.session_state.get(f"pending_exit_{group_id}", {})
        leg_pending = pending_data.get(leg.id)

        if leg_pending:
            # use what the the user typed before
            default_price = float(leg_pending['price'])
            default_comm = float(leg_pending['commission'])
        else:      
            # LOOKUP: Find the live price passed from the main UI
            matching_price_data = next((item for item in active_prices if item['leg_id'] == leg.id), None)
            
            # Use the match price, or fallback to 0.0 if not found
            if matching_price_data and matching_price_data.get('live_price') is not None:
                #default_price = float(matching_price_data['live_price']) if matching_price_data else 0.0
                default_price = float(matching_price_data['live_price'])
            elif leg.entry_price:
                default_price = float(leg.entry_price)
            else:
                default_price = 0.0

            default_comm = OPTIONS_COMMISSION

        # UI: Compact row per leg
        with st.container():
            # Bold label for the leg
            st.markdown(f"**Leg:** {leg.symbol} {leg.strikeprice}{leg.option_type} ({leg.side})")
            leg_str = f"{leg.strikeprice}{leg.option_type} ({leg.side})"
        
            col1, col2 = st.columns(2)
            with col1:
                price = st.number_input(
                    f"Exit Price for {leg_str}", 
                    value=default_price,
                    format="%.2f",
                    key=f"exit_p_{leg.id}_{group_id}",
                    label_visibility="collapsed"
                )
            with col2:
                comm = st.number_input(
                    f"Exit Comm for {leg_str}", 
                    value=default_comm, 
                    format="%.2f",
                    key=f"exit_c_{leg.id}_{group_id}",
                    label_visibility="collapsed"
                )
            exit_details[leg.id] = {"price": price, "commission": comm}

            if i < len(active_legs) - 1:
                st.write("") # Tiny spacer instead of heavy divider

    if st.button("Review Summary", type="primary", width='stretch'):
        try:
            # Parse time string back to a datetime object
            trade_time_obj = datetime.strptime(trade_time_str.strip(), "%H:%M:%S").time()
            execution_dt = est_tz.localize(datetime.combine(trade_date, trade_time_obj))

            # Temporary "What-If calculation using your correct P&L engine
            # Pass our manual exit prices as if they were 'live_price' to see the simulated result
            simulated_active_data = [{'leg_id': k, 'live_price': v['price']} for k, v in exit_details.items()]
            final_stats = calculate_comprehensive_pnl(group_id, simulated_active_data)

            # Calculate P&L %
            final_stats['pnl_pct'] = (final_stats['total_pnl'] / abs(final_stats['initial_debit'])) * 100 if final_stats['initial_debit'] != 0 else 0

            # Store in session state and flip view
            st.session_state[f"execution_dt_{group_id}"] = execution_dt
            st.session_state[f"final_results_{group_id}"] = final_stats
            st.session_state[f"pending_exit_{group_id}"] = exit_details
            st.session_state[f"summary_view_{group_id}"] = True

            logger.debug(f"Saved state for {group_id}: Date={trade_date}, Time={trade_time_str}")

            st.rerun()
        except ValueError:
                st.error("Invalid time format. Please use HH:MM:SS.")

    if st.button("Cancel", width='stretch'):
        for key in [f"summary_view_{group_id}", f"active_dialog_{group_id}", 
                    f"final_results_{group_id}", f"pending_exit_{group_id}"]:
            if key in st.session_state: 
                del st.session_state[key]
        st.rerun()

def render_dynamic_leg_form(underlying_ticker):
    """Renders a dynamic form for 1 to 4 legs."""
    if "dynamic_legs" not in st.session_state:
        # Default to 2 legs to match your current Bull Put/Calendar logic
        st.session_state.dynamic_legs = [
            {"side": "STO", "qty": -1.0, "exp": "", "stk": 0.0, "type": "Call", "price": 0.0, "comm": 0.65},
            {"side": "BTO", "qty": 1.0, "exp": "", "stk": 0.0, "type": "Call", "price": 0.0, "comm": 0.65}
        ]

    to_delete = None

    with st.container():
        st.markdown("### 🧬 Strategy Legs")
    
        for idx, leg in enumerate(st.session_state.dynamic_legs):
            c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1.2, 1.8, 1.2, 1.2, 1, 1, 1, 0.5])
            
            leg['side'] = c1.selectbox("Side", ["BTO", "STO", "BUY", "SELL"], index=0, key=f"side_{idx}")
            leg['exp'] = c2.text_input("Expiry", value=leg['exp'], key=f"exp_{idx}")
            leg['stk'] = c3.number_input("Strike", value=float(leg['stk']), key=f"stk_{idx}")
            leg['type'] = c4.selectbox("Type", ["Call", "Put"], key=f"type_{idx}")
            leg['qty'] = c5.number_input("Qty", value=float(leg['qty']), key=f"qty_{idx}")
            leg['price'] = c6.number_input("Price", value=float(leg['price']), key=f"price_{idx}")
            leg['comm'] = c7.number_input("Comm", value=float(leg['comm']), key=f"comm_{idx}")
            
            if c8.button("🗑️", key=f"del_{idx}"):
                to_delete = idx

        if to_delete is not None:
            st.session_state.dynamic_legs.pop(to_delete)
            st.rerun()

        if st.button("➕ Add Leg"):
            st.session_state.dynamic_legs.append({"side": "BTO", "qty": 1.0, "exp": "", "stk": 0.0, "type": "Call", "price": 0.0, "comm": 0.65})
            st.rerun()
            
    return st.session_state.dynamic_legs

def show_trade_confirmation(message: str, success_type: str = "toast", show_balloons: bool = False):
    """
    Unified UI utility for trade actions (Entry, Exit, Adjustments).
    
    Args:
        message (str): The text to display.
        success_type (str): "toast" for a popup, "box" for st.success, or "both".
        show_balloons (bool): If True, triggers the celebration animation.
    """
    
    # 1. Trigger Animations first
    if show_balloons:
        st.balloons()

    # 2. Handle the display type
    if success_type in ["toast", "both"]:
        # We use a standard icon for all trade actions to keep it branded
        st.toast(message, icon="✅")

    if success_type in ["box", "both"]:
        st.success(message)
        
    # 3. Small sleep to allow the user to 'register' the success before a rerun
    # (Only needed if you are calling st.rerun() immediately after)
    time.sleep(0.5)