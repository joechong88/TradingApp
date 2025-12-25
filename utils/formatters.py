import math
import pandas as pd
import re

import re

def is_valid_expiry(expiry_str):
    """
    Validates YYYYMMDD format:
    - Exactly 8 digits
    - Year starts with 20
    - Month 01-12
    - Day 01-31
    """
    pattern = r"^20\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$"
    return re.match(pattern, expiry_str) is not None
    
def format_currency(val):
    """
    Format a numeric value as $X,XXX.XX.
    - Handles None, NaN, and NaT gracefully.
    - Adds commas for thousands and fixes to 2 decimal places.
    """
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    try:
        return f"${val:,.2f}"
    except Exception:
        return str(val)

def format_percentage(val):
    """
    Format a numeric value as XX.XX%.
    - Handles None/NaN safely.
    """
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    try:
        return f"{val:.2f}%"
    except Exception:
        return str(val)

def format_datetime(dt):
    """
    Format a pandas Timestamp or datetime into YYYY-MM-DD HH:MM:SS.
    - Returns empty string if None/NaT.
    """
    if dt is None or pd.isna(dt):
        return ""
    try:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(dt)

def format_pnl(val):
    """
    Format PnL as currency with sign.
    - Positive → $X.XX
    - Negative → -$X.XX
    - Zero/None → $0.00 or blank
    """
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    try:
        return f"${val:,.2f}" if val >= 0 else f"-${abs(val):,.2f}"
    except Exception:
        return str(val)

# Style: right-align currency and color-code PnL
def pnl_color(val):
    if pd.isna(val):   # negative
        return ""
    if val < 0:
        return "color: red; text-align: right;"
    elif val > 0:  # positive or zero
        return "color: green; text-align: right;"
    return "text-align: right;"

# expiry color for options remaining days to expire
def expiry_color(val: int) -> str:
    if val is None or pd.isna(val):
        return ""
    if val < 5:
        return "background-color: red; color: white;"
    elif val < 30:
        return "background-color: orange; color: black;"
    else:
        return "background-color: green; color: white;"