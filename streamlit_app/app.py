import asyncio

# Ensure an event loop exists in Streamlit's script thread
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
from dotenv import load_dotenv
from db.models import init_db

load_dotenv()
st.set_page_config(page_title="Trading App", layout="wide")

# Initialize DB on startup
init_db()

st.markdown("# Trading App")
st.write("Use the sidebar to navigate: Home, New Trade, Open, Cosed Trades, Dashboard or DB Utilities.")