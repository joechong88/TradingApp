import toml  # Available in Python 3.11+
import os
import streamlit as st

CONFIG_PATH = "config.toml"

def load_config():
    # Try to load from Streamlit Secrets (Cloud)
    if "targets" in st.secrets or "fees" in st.secrets:
        return {
            "targets": {
                "stock_pnl_target": st.secrets.get("targets", {}).get("stock_pnl_target", 600.0),
                "max_risk_per_trade": st.secrets.get("targets", {}).get("max_risk_per_trade", 100.0)
            },
            "fees": {
                "option_commission": st.secrets.get("fees", {}).get("option_commission", 0.65),
                "stock_commission": st.secrets.get("fees", {}).get("stock_commission", 1.0)
            }
        }
    
    # 2. Fallback to local config.toml (Local Development)
    if os.path.exists(CONFIG_PATH):
        # Empathy for the system: provide safe defaults if file is missing
        return toml.load(CONFIG_PATH)

    # 3. Final Fallback    
    return {
        "targets": {"stock_pnl_target": 600.0, "max_risk_per_trade": 100.0},
        "fees": {"option_commission": 0.65, "stock_commission": 1.0}
    }
    

def save_config_local(config_dict):
    try:
        with open(CONFIG_PATH, "w") as f:
            toml.dump(config_dict, f)
        return True
    except Exception:
        return False