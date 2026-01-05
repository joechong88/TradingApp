import toml  # Available in Python 3.11+
import os
import streamlit as st

CONFIG_PATH = "config.toml"

def load_config():
    # Try to load from Streamlit Secrets (Cloud)
    if "targets" in st.secrets:
        # Convert Secrets object to a standard dictionary
        return {
            "targets": {
                "stock_pnl_target": st.secrets["targets"].get("stock_pnl_target", 500.0)
            }
        }

    # 2. Fallback to local config.toml (Local Development)
    if os.path.exists(CONFIG_PATH):
        # Empathy for the system: provide safe defaults if file is missing
        return toml.load(CONFIG_PATH)

    # 3. Final Fallback    
    return {"targets": {"daily_stock_pnl": 500.0}}
    

def save_config_local(config_dict):
    try:
        with open(CONFIG_PATH, "w") as f:
            toml.dump(config_dict, f)
        return True
    except Exception:
        return False