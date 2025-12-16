import asyncio

# ✅ Ensure Streamlit’s ScriptRunner thread has an event loop
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from ib_insync import IB
import time
from utils.logger import get_logger

logger = get_logger(__name__)

def connect_ib() -> IB:
    """
    Bulletproof IBKR connector:
    - Ensures clean event loop for Streamlit
    - Avoids stale global IB() instances
    - Tries all valid IBKR ports (4001, 4002, 7496, 7497)
    - Avoids clientId collisions
    - Verifies connection before returning
    """

    ib = IB()  # fresh instance every time

    ports = [4001, 7496, 4002, 7497]    # live/paper
    client_ids = range(8, 10)

    for port in ports:
        for client_id in client_ids:  # avoid collisions
            try:
                logger.info(f"Trying IBKR: port={port}, clientId={client_id}")
                
                # ensure clean state
                try:
                    ib.disconnect()
                except Exception:
                    pass

                ib.connect("127.0.0.1", port, clientId=client_id, timeout=3)

                # MUST check this — connect() does NOT throw on failure
                if ib.isConnected():
                    logger.info(f"Connected to IBKR on port {port} (clientId={client_id}), "
                                f"ib id={id(ib)}"
                    )
                    return ib
            except Exception as e:
                logger.warning(f"Failed on port {port}, clientId={client_id}: {e}")
            time.sleep(0.2)

    msg = (
        "Could not connect to IB Gateway or TWS on ANY port "
        "(4001, 4002, 7496, 7497). Check API settings and Gateway mode."
    )
    logger.error(msg)
    raise ConnectionError(msg)