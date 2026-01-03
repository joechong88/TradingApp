import streamlit as st
from config_loader import load_config, save_config

st.title("⚙️ App Settings")

# Load current state
config = load_config()

st.header("Trading Targets")
current_target = config["targets"]["stock_pnl_target"]

# User input for the target
new_target = st.number_input(
    "Stock P&L Target ($)", 
    value=float(current_target),
    step=50.0
)

if st.button("Save Settings"):
    config["targets"]["stock_pnl_target"] = new_target
    save_config(config)
    st.success(f"Target updated to ${new_target}! Restart app or refresh to apply.")
    st.balloons()