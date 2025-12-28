import streamlit as st

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
