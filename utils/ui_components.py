import streamlit as st
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
