import streamlit as st
from utils.config_loader import load_config, save_config
import os

st.title("⚙️ App Settings")

# Load current state
config = load_config()

st.header("Trading Targets")
targets = config.get("targets", {})
current_target = targets.get("stock_pnl_target", 500.0)

# User input for the target
new_target = st.number_input(
    "Stock P&L Target ($)", 
    value=float(current_target),
    step=50.0
)

if st.button("Save Settings"):
    # Always update Session State for immediate effect across all pages
    st.session_state.stock_pnl_target = new_target

    # 2. Try to save locally if not on Streamlit Cloud
    # Streamlit Cloud sets specific environment variables we can check
    is_cloud = os.getenv("STREAMLIT_RUNTIME_ENV_REMOTE") == "true" or "STREAMLIT_SERVER_PORT" not in os.environ

    if not is_cloud:
        success = save_config_local({"targets": {"stock_pnl_target": new_target}})
        if success:
            st.success("✅ Local config.toml updated permanently!")
        else:
            st.error("❌ Failed to write to config.toml")
    else:
        st.info("☁️ Running on Cloud: Target updated for this session. To make it permanent, update your 'Secrets' in the Dashboard.")
    
    st.balloons()