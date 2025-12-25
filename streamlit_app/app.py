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
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import time
import toml
from dotenv import load_dotenv
from db.models import init_db

def check_password():
    """Returns True if the user entered the correct password."""

    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if not st.session_state.password_correct:
        st.title("🔒 Secure Login")

        password = st.text_input("Enter password", type="password")

        if password == st.secrets.get("APP_PASSWORD", "devpassword"):
            st.session_state.password_correct = True
        else:
            if password:
                st.error("Incorrect password")

        return False

    return True

# Load config from secrets
config = toml.load(".streamlit/secrets.toml")

# Create authenticator
authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"],
)
#import inspect
#sig = inspect.signature(authenticator.login)
#print("LOGIN SIGNATURE:", sig)

# Login widget
login_result = authenticator.login(location="main")
if login_result is None:
    st.stop()

# Unpack the result
name, auth_status, username = login_result

# Handle login states
if auth_status is False:
    st.error("Incorrect username or password")
elif auth_status is None:
    st.warning("Please enter your username and password")
elif auth_status:
    authenticator.logout(location="main")
    st.sidebar.write(f"Welcome, {name}!")

# Stop the app unless the password is correct
if not check_password():
    st.stop()

SESSION_TIMEOUT_MINUTES = 30

if "last_activity" not in st.session_state:
    st.session_state.last_activity = time.time()

# Check timeout
if time.time() - st.session_state.last_activity > SESSION_TIMEOUT_MINUTES * 60:
    st.warning("Session timed out. Please log in again.")
    authenticator.logout("Logout", "main")
    st.stop()

# Update activity timestamp
st.session_state.last_activity = time.time()

load_dotenv()
st.set_page_config(page_title="Trading App", layout="wide")

# Initialize DB on startup
init_db()

st.markdown("# Trading App")
st.write("Use the sidebar to navigate: Home, New Trade, Open, Cosed Trades, Dashboard or DB Utilities.")