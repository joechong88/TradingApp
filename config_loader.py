import toml  # Available in Python 3.11+
import os

CONFIG_PATH = "config.toml"

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.toml")

    if not os.path.exists(CONFIG_PATH):
        # Empathy for the system: provide safe defaults if file is missing
        return {"targets": {"daily_stock_pnl": 500.0}}
    return toml.load(CONFIG_PATH)

def save_config(config_dict):
    with open(CONFIG_PATH, "w") as f:
        toml.dump(config_dict, f)