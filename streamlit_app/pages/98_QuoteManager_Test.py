import asyncio

# ✅ Ensure Streamlit’s ScriptRunner thread has an event loop
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import streamlit as st

import time
from utils.quote_manager import QuoteManager
from ib_insync import Stock, Option, IB

from utils.logger import get_logger

# --- Initiate logging
logger = get_logger(__name__)
logger.debug("Starting QuoteManager Test page")

# ---------------------------------------------------------
# ✅ Symbols to test (same as test_data.py)
# ---------------------------------------------------------

tests = [
#    ("TSLA", None, None, None),
#    ("TSLA", "20260102", 500.0, "C"),
    ("CRCL", None, None, None),
    ("CRCL", "20260123", 93.0, "C"),
    ("SOFI", "20260116", 32.0, "C"),
    ("CRWD", "20260116", 470.0, "P"),
#    ("NFLX", "20260102", 92.5, "P"),
#    ("AAPL", "20260123", 290.0, "C"),
    ("APLD", "20260109", 24.5, "P"),
#    ("ONDS", "20260102", 7.0, "P"),
#    ("CLS", "20260102", 290.0, "P"),
#    ("IREN", "20260102", 41.0, "P"),
    ("HOOD", "20251226", 120.0, "P"),
    ("HOOD", "20260320", 120.0, "C"),
]

st.set_page_config(page_title="QuoteManager Market Data Test", layout="wide")

st.title("🧪 QuoteManager vs test_data.py — Market Data Comparison")

st.markdown("""
This page runs **the same symbols** as your standalone `test_data.py` and compares:

- ✅ QuoteManager output  
- ✅ Raw IBKR output (using direct IB() calls)  
- ✅ LIVE / FROZEN / DELAYED behavior  
- ✅ last / bid / ask / close  
- ✅ Greeks (for options)  

This helps confirm whether QuoteManager is receiving the same data stream as your standalone script.
""")

# ---------------------------------------------------------
# ✅ Initialize QuoteManager
# ---------------------------------------------------------
# ---------------------------------------------------------
# Initialize persistent QuoteManager (same pattern as dashboard)
# ---------------------------------------------------------
if "qm" not in st.session_state:
    st.session_state.qm = QuoteManager()

qm = st.session_state.qm
st.write(f"QuoteManager IB id: {id(qm.ib)}  |  version={qm.version}")
st.info(f"QM version={qm.version}, tickers={len(qm.tickers)}, cache={len(qm.cache)}")

# Sidebar Health Check
status, icon, sess = qm.get_status()
st.sidebar.metric("IBKR Status", f"{icon} {status}", f"Session: {sess}")

if st.sidebar.button("Hard Reset Connection"):
    qm.reset()
    st.rerun()

# ---------------------------------------------------------
# ✅ Helper: run raw IBKR test (like test_data.py)
# ---------------------------------------------------------
def run_raw_ib_test(contract):
    ib = IB()
    st.write(f"Raw IB id: {id(ib)}")

    ports = [4001, 7496]

    for port in ports:
        try:
            ib.disconnect()  # ensure clean state
        except Exception:
            pass

        try:
            ib.connect("127.0.0.1", port, clientId=99, timeout=3)
            if ib.isConnected():
                logger.info(f"[run_raw_ib_test] Connected on port {port}, ib id={id(ib)}")
                connected = True
                break
        except Exception as e:
            logger.warning(f"[run_raw_ib_test] Failed to connect on port {port}: {e}")

    if not connected:
        st.error("❌ Could not connect to IBKR on ports 4001 or 7496.")
        return {
            "LIVE": {},
            "FROZEN": {},
            "DELAYED": {}
        }
    
    logger.info(f"[run_raw_ib_test] ib id={id(ib)}")

    results = {}

    for md_type, label in [(1, "LIVE"), (2, "FROZEN"), (3, "DELAYED")]:
        logger.info(f"[run_raw_ib_test] Request market_type={md_type} for {contract}")
        ib.reqMarketDataType(md_type)
        ticker = ib.reqMktData(contract, snapshot=False)

        # wait up to 2 seconds
        for _ in range(20):
            ib.sleep(0.1)
            if any([ticker.last, ticker.bid, ticker.ask, ticker.close]):
                break

        results[label] = {
            "last": ticker.last,
            "bid": ticker.bid,
            "ask": ticker.ask,
            "close": ticker.close,
            "modelGreeks": str(ticker.modelGreeks)
        }

    ib.disconnect()
    return results

run_button = st.button("Run Full Comparison")
run_button_2 = st.button("Run Raw Test using QuoteManager.ib")
reset_button = st.button("Reset QuoteManager (Test)")

if run_button:
    for symbol, expiry, strike, right in tests:
        st.markdown("---")
        st.subheader(f"🔎 Testing {symbol} {expiry or ''} {strike or ''} {right or ''}")

        # ---------------------------------------------------------
        # ✅ Build contract
        # ---------------------------------------------------------
        if expiry and strike and right:
            contract = Option(symbol, expiry, float(strike), right, "SMART", 100.0, "USD")
        else:
            contract = Stock(symbol, "SMART", "USD")

        # ---------------------------------------------------------
        # ✅ Run QuoteManager
        # ---------------------------------------------------------
        #st.markdown("### ✅ QuoteManager Output")
        start = time.time()
        qm_quote = qm.safe_get_quote(symbol, expiry=expiry, strike=strike, right=right)
        qm_time = time.time() - start

        st.json({
            "quote": qm_quote,
            "time_taken": qm_time,
            "qm_version": qm.version
        })

        # ---------------------------------------------------------
        # ✅ Run raw IBKR test (like test_data.py)
        # ---------------------------------------------------------
        #st.markdown("### ✅ Raw IBKR Output (same as test_data.py)")
        raw_results = run_raw_ib_test(contract)
        st.json(raw_results)

        # ---------------------------------------------------------
        # ✅ Comparison Table
        # ---------------------------------------------------------
        st.markdown("### ✅ Side-by-Side Comparison")

        def safe(v):
            return None if v is None else v

        comparison = {
            "QuoteManager_last": safe(qm_quote.get("last") if qm_quote else None),
            "QuoteManager_bid": safe(qm_quote.get("bid") if qm_quote else None),
            "QuoteManager_ask": safe(qm_quote.get("ask") if qm_quote else None),
            "QuoteManager_close": safe(qm_quote.get("close") if qm_quote else None),
            "Raw_LIVE_last": safe(raw_results["LIVE"]["last"]),
            "Raw_DELAYED_last": safe(raw_results["DELAYED"]["last"]),
            "Raw_DELAYED_close": safe(raw_results["DELAYED"]["close"]),
        }

        st.json(comparison)
    logger.info(f"[run_button] COMPLETED")

if run_button_2:
    qm.ensure_connected() 
    ib = qm.ib

    from ib_insync import Stock, IB
    contract = Stock("AAPL", "SMART", "USD")

    ib.reqMarketDataType(3)
    ticker = ib.reqMktData(contract, snapshot=False)

    for i in range(20):
        ib.sleep(0.1)
        st.write(
            f"tick {i}: last={ticker.last}, bid={ticker.bid}, "
            f"ask={ticker.ask}, close={ticker.close}"
        )

if reset_button:
    qm.reset()
    st.success(f"QuoteManager reset. New version={qm.version}")
    st.rerun()