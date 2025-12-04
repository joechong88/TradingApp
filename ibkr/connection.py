import os
import asyncio

# --- Ensure an event loop exists in Streamlit's script thread ---
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# --- Now safe to import ib_insync and your IBKR helpers ---

from ib_insync import IB
from dotenv import load_dotenv

_ib_instance = None

ib = IB()

def connect_ib():
    """
    Try connecting to IB Gateway (4001) first, then TWS (7694).
    Returns the connected IB instance.
    """
    if ib.isConnected():
        return ib

    try:
        ib.connect('127.0.0.1', 4001, clientId=1)
        print("Connected to IB Gateway on port 4001")
    except Exception as e1:
        print("IB Gateway not available:", e1)
        try:
            ib.connect('127.0.0.1', 7694, clientId=1)
            print("Connected to TWS on port 7694")
        except Exception as e2:
            raise ConnectionError(
                f"Could not connect to IB Gateway (4001) or TWS (7694): {e2}"
            )
    return ib

def get_ib() -> IB:
    global _ib_instance
    if _ib_instance:
        return _ib_instance

    load_dotenv()
    enable = os.getenv("IB_ENABLE", "True").lower() == "true"
    if not enable:
        raise RuntimeError("IBKR connectivity disabled via IB_ENABLE.")

    host = os.getenv("IB_HOST", "127.0.0.1")
    port = int(os.getenv("IB_PORT", "4001"))
    client_id = int(os.getenv("IB_CLIENT_ID", "1"))

    ib = IB()
    ib.connect(host, port, clientId=client_id)
    _ib_instance = ib
    return ib