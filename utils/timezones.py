import pytz
from datetime import datetime

ET = pytz.timezone("US/Eastern")
UTC = pytz.utc

def now_et():
    return datetime.now(ET)

def to_et(dt):
    if dt.tzinfo is None:
        dt = UTC.localize(dt)
    return dt.astimezone(ET)

def is_us_equity_session(dt_et: datetime):
    # Simple check: 9:30–16:00 ET Monday–Friday
    wd = dt_et.weekday()  # 0=Mon
    if wd > 4:
        return False
    open_t = dt_et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = dt_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= dt_et <= close_t