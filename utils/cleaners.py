import math
import pandas as pd

def is_nan(val):
    """Check if a value is NaN (float) or NaT (pandas Timestamp)."""
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    if isinstance(val, pd.Timestamp) and pd.isna(val):
        return True
    return False

def clean_numeric(val):
    """
    Convert strings with $ or commas to float, handle NaN/None/-1.
    """
    if val is None:
        return None

    # Convert strings
    if isinstance(val, str):
        val = val.replace("$", "").replace(",", "").strip()
        if val == "":
            return None
        try:
            val = float(val)
        except Exception:
            return None

    # Now val is numeric or NaN
    if isinstance(val, (int, float)):
        if math.isnan(val):
            return None
        if val == -1:   # IBKR's "no bid/ask" sentinel
            return None
        return float(val)

    return None

def clean_datetime(date_val, time_val=None):
    """
    Combine date + time into datetime, handle NaN/NaT/None.
    Returns None if missing or invalid.
    """
    if is_nan(date_val) and is_nan(time_val):
        return None
    try:
        if date_val and time_val and not is_nan(date_val) and not is_nan(time_val):
            dt = pd.to_datetime(f"{date_val} {time_val}", errors="coerce")
        elif date_val and not is_nan(date_val):
            dt = pd.to_datetime(date_val, errors="coerce")
        else:
            return None
        return None if pd.isna(dt) else dt
    except Exception:
        return None

def clean_bool(val):
    """Map OPEN/TRUE/1 → True, else False. Default True if None."""
    if is_nan(val):
        return True
    return str(val).strip().upper() in ["OPEN", "TRUE", "1"]

def clean_str(val):
    """Convert NaN/NaT to None, keep strings."""
    if is_nan(val):
        return None
    return str(val).strip()