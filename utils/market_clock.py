import streamlit as st
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timedelta
import pytz
import pandas_market_calendars as mcal 
import threading
import time

def _render_clock(now_et):
    """Return HTML markup for the market clock banner."""
    nyse = mcal.get_calendar("NYSE")
    schedule = nyse.schedule(start_date=now_et.date(), end_date=now_et.date())

    status, color, countdown_msg = "Market Closed", "red", ""

    # Weekend check
    if now_et.weekday() >= 5:
        status, color = "Weekend - Market Closed", "red"
        days_ahead = 7 - now_et.weekday()
        next_open = (now_et + timedelta(days=days_ahead)).replace(hour=9, minute=30, second=0, microsecond=0)
        delta = next_open - now_et
        countdown_msg = "📈 Market Opening Now!" if delta.total_seconds() <= 0 else \
            f"Next open in {delta.days}d {delta.seconds//3600}h {(delta.seconds//60)%60}m"

    else:
        if schedule.empty:
            status, color = "Holiday - Market Closed", "red"
            countdown_msg = "Next open: after holiday (check NYSE calendar)"
        else:
            rth_start = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
            rth_end   = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
            pre_start = now_et.replace(hour=4, minute=0, second=0, microsecond=0)
            pre_end   = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
            after_start = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
            after_end   = now_et.replace(hour=20, minute=0, second=0, microsecond=0)

            if rth_start <= now_et <= rth_end:
                status, color = "Regular Trading Hours", "green"
                delta = rth_end - now_et
                countdown_msg = "🔒 Market Closing Now!" if delta.total_seconds() <= 0 else \
                    f"Closes in {delta.seconds//3600}h {(delta.seconds//60)%60}m {delta.seconds%60}s"
            elif pre_start <= now_et < pre_end:
                status, color = "Pre-Market Trading Hours", "orange"
                delta = rth_start - now_et
                countdown_msg = "📈 Market Opening Now!" if delta.total_seconds() <= 0 else \
                    f"Opens in {delta.seconds//3600}h {(delta.seconds//60)%60}m {delta.seconds%60}s"
            elif after_start < now_et <= after_end:
                status, color = "After-Hours Trading", "orange"
                delta = after_end - now_et
                countdown_msg = "🔒 Market Closing Now!" if delta.total_seconds() <= 0 else \
                    f"Closes in {delta.seconds//3600}h {(delta.seconds//60)%60}m {delta.seconds%60}s"
            else:
                status, color = "Closed (Outside Trading Hours)", "red"
                next_open = (now_et + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
                delta = next_open - now_et
                countdown_msg = "📈 Market Opening Now!" if delta.total_seconds() <= 0 else \
                    f"Next open in {delta.seconds//3600}h {(delta.seconds//60)%60}m {delta.seconds%60}s"

    return f"""
    <div style="font-size:14px;font-weight:bold;padding:10px;border-radius:8px;background-color:{color};color:white;text-align:center;">
        🕒 <b>Eastern Time:</b> {now_et.strftime("%Y-%m-%d %H:%M:%S %Z")}<br>
        <b>Market Status:</b> {status}<br>
        ⏳ {countdown_msg}
    </div>
    """

def show_market_clock(interval=60, mode="autorefresh"):
    """
    Display a market clock banner.
    - mode="autorefresh": reruns the page every `interval` seconds.
    - mode="static": renders once (snapshot).
    """
    eastern = pytz.timezone("US/Eastern")

    if mode == "autorefresh":
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=interval*1000, key="market_clock_refresh")

    now_et = datetime.now(eastern)
    st.markdown(_render_clock(now_et), unsafe_allow_html=True)