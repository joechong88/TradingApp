from datetime import datetime
from .timezones import to_et, now_et

def validate_entry_timestamp(entry_dt: datetime):
    entry_et = to_et(entry_dt)
    current_et = now_et()
    if entry_et > current_et:
        raise ValueError(f"Entry timestamp {entry_et} is in the future relative to ET {current_et}.")
    return entry_et