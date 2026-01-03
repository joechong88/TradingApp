import streamlit as st
import pandas as pd
from utils.trades import calculate_strategy_cost

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

def render_complex_strategy_cards(complex_groups):
    """
    Reusable UI component to display complex option strategies in a row-based format.
    """
    if not complex_groups:
        st.info("No open complex strategies found.")
        return

    st.header("Complex Options Strategies")
    
    for group in complex_groups:
        # 1. Data Preparation
        note_preview = group.notes[:30] if group.notes else "No notes"
        ticker = group.legs[0].symbol[:6].strip() if group.legs else "Data Error"
        cost_info = calculate_strategy_cost(group.legs)

        # 2. Expander Header
        expander_label = f"**Group ID:** {group.id} | **{ticker}** | {group.strategy_name} | *{note_preview}*"
        
        with st.expander(expander_label, expanded=False):
            st.write(f"**Trade Thesis:** {group.notes if group.notes else 'N/A'}")

            # 3. Full-Width Table Row
            leg_data = []
            for leg in group.legs:
                # Concatenate details
                details = f"{leg.expiry_dt or 'N/A'} {leg.strikeprice or ''} {leg.option_type or ''}".strip()
                
                leg_data.append({
                    "Symbol": leg.symbol,
                    "Details": details,
                    "Action": leg.side,
                    "Quantity": leg.quantity,
                    "Price": f"${leg.entry_price:.2f}" if leg.entry_price is not None else "N/A",
                    "Commission": f"${leg.entry_commission:.2f}" if leg.entry_commission is not None else "N/A",
                    "Status": leg.status
                })
            st.table(leg_data)

            st.divider()

            # 4. Action & Metric Row
            col_met, col_btn1, col_btn2 = st.columns([2, 1, 1])

            with col_met:
                st.metric(
                    label=cost_info["label"],
                    value=cost_info["formatted_abs"],
                    help=f"Actual cash impact including the 100x multiplier"
                )
                if cost_info["commissions"] > 0:
                    st.caption(f"Friction: ${cost_info['commissions']:.2f}")

            with col_btn1:
                # Buttons use the group.id to ensure unique keys
                if st.button("Roll Short Leg", key=f"roll_{group.id}", use_container_width=True):
                    st.info(f"Rolling logic for Group {group.id} coming soon!")

            with col_btn2:
                if st.button("Close Strategy", key=f"close_{group.id}", use_container_width=True):
                    # In the future, you can trigger a callback or session_state change here
                    st.session_state[f"confirm_close_{group.id}"] = True
                    st.warning(f"Closing Group {group.id}...")

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
    })
    
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
    
    # --- 2. Render Form Inputs ---
    sel_label = st.selectbox("Select trade ID to close", list(trade_map.keys()))
    sel_id = trade_map[sel_label]
    
    col1, col2 = st.columns(2)
    with col1:
        exit_price = st.number_input("Exit price", min_value=0.0, step=0.01)
        st.date_input("Exit date (ET assumed)", key="exit_date")
    with col2:
        exit_commissions = st.number_input("Exit Commissions", min_value=0.0, step=0.01)
        st.text_input("Exit time (HH:MM:SS) (ET assumed)", key="exit_time")

    # --- 3. Process Closing ---
    if st.button("Close trade", use_container_width=True):
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
                    st.success(f"Trade {sel_id} closed successfully!")
                    st.balloons()
                    st.rerun() # Refresh to update the table
        except ValueError:
            st.error("Invalid time format. Please use HH:MM:SS.")