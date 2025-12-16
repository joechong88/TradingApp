import streamlit as st
import time
from utils.quote_manager import QuoteManager

st.set_page_config(page_title="IBKR Market Data Diagnostics", layout="wide")

st.title("🔍 IBKR Market Data Diagnostics Panel")

st.markdown("""
Use this panel to inspect raw IBKR market data, session detection, contract qualification, 
and synthetic price logic. This helps verify whether your API session is receiving 
LIVE, FROZEN, or DELAYED data correctly.
""")

# -----------------------------
# ✅ User Inputs
# -----------------------------
st.sidebar.header("Symbol Settings")

symbol = st.sidebar.text_input("Symbol", "AAPL")
expiry = st.sidebar.text_input("Expiry (YYYYMMDD, optional)", "")
strike = st.sidebar.text_input("Strike (optional)", "")
right = st.sidebar.selectbox("Right (optional)", ["", "C", "P"])

run_button = st.sidebar.button("Run Diagnostics")

# -----------------------------
# ✅ QuoteManager Instance
# -----------------------------
qm = QuoteManager()

# -----------------------------
# ✅ Run Diagnostics
# -----------------------------
if run_button:

    st.subheader("📡 Running Diagnostics…")

    # Convert strike to float if provided
    strike_val = float(strike) if strike else None
    expiry_val = expiry if expiry else None
    right_val = right if right else None

    start = time.time()
    quote = qm.safe_get_quote(
        symbol=symbol,
        expiry=expiry_val,
        strike=strike_val,
        right=right_val
    )
    elapsed = time.time() - start

    if quote is None:
        st.error("❌ No quote returned. Check logs for details.")
        st.stop()

    # -----------------------------
    # ✅ Display Results
    # -----------------------------
    st.success("✅ Diagnostics Complete")

    st.markdown(f"### Symbol: **{symbol}**")
    st.markdown(f"**Session:** `{quote.get('session')}`")
    st.markdown(f"**Time Taken:** `{elapsed:.3f} seconds`")

    # -----------------------------
    # ✅ Raw Ticker Data
    # -----------------------------
    st.subheader("📊 Raw Market Data")

    raw_cols = st.columns(4)
    raw_cols[0].metric("Last", quote.get("last"))
    raw_cols[1].metric("Bid", quote.get("bid"))
    raw_cols[2].metric("Ask", quote.get("ask"))
    raw_cols[3].metric("Close", quote.get("close"))

    # -----------------------------
    # ✅ Greeks (if options)
    # -----------------------------
    if quote.get("delta") is not None:
        st.subheader("📐 Option Greeks")
        greek_cols = st.columns(5)
        greek_cols[0].metric("Delta", quote.get("delta"))
        greek_cols[1].metric("Gamma", quote.get("gamma"))
        greek_cols[2].metric("Vega", quote.get("vega"))
        greek_cols[3].metric("Theta", quote.get("theta"))
        greek_cols[4].metric("IV", quote.get("iv"))
    else:
        st.info("No Greeks available (likely a stock or delayed data).")

    # -----------------------------
    # ✅ Full Quote JSON
    # -----------------------------
    st.subheader("🧩 Full Quote Object")
    st.json(quote)

    # -----------------------------
    # ✅ Debug Info
    # -----------------------------
    st.subheader("🛠 Debug Info")
    st.code(f"""
Session detected: {quote.get('session')}
Synthetic last: {quote.get('last')}
Bid/Ask: {quote.get('bid')} / {quote.get('ask')}
Close: {quote.get('close')}
Greeks: {quote.get('delta')}, {quote.get('gamma')}, {quote.get('vega')}, {quote.get('theta')}
""")