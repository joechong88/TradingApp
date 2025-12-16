import asyncio

# ✅ Ensure Streamlit’s ScriptRunner thread has an event loop
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from ib_insync import IB, Stock, Option

import time
import pandas_market_calendars as mcal 
import pytz
import math

from threading import Lock
from datetime import datetime, timedelta
from utils.ibkr import connect_ib
from utils.logger import get_logger
from utils.cleaners import clean_numeric

logger = get_logger(__name__)

class QuoteManager:
    """
    Streamlit‑safe, fault‑tolerant IBKR Quote Manager.
    - Auto‑reconnects when IBKR drops.
    - Prevents Streamlit freezes.
    - Ensures only one subscription per contract.
    - Cleans up stale tickers.
    """
    def __init__(self):
        self.ib: IB | None = None  # this now binds to the existing loop
        self.cache = {}
        self.tickers = {}
        self.lock = Lock()
        self.current_session = None
        logger.info(f"[QuoteManager.__init__] self.ib id={id(self.ib)}")


    # ---------------------------------------------------------
    # ✅ Auto‑Reconnect (critical for Streamlit)
    # ---------------------------------------------------------
    def ensure_connected(self):
        if self.ib is None:
            logger.info("[QuoteManager.ensure_connected] self.ib is None, connecting...")
            self.ib = connect_ib()
            logger.info(
                f"[QuoteManager.ensure_connected] new IB instance id={id(self.ib)}, "
                f"isConnected={self.ib.isConnected()}"
            )
            return

        # Existing IB but disconnected
        if not self.ib.isConnected():
            logger.info(
                f"[QuoteManager.ensure_connected] Existing IB disconnected, "
                f"reconnecting... id={id(self.ib)}"
            )
            self.ib = connect_ib()  # Create IB only here
            logger.info(
                f"[QuoteManager.ensure_connected] reconnected IB id={id(self.ib)}, "
                f"isConnected={self.ib.isConnected()}"
            )

    def get_market_session(self):
        """
        Returns one of:
            "regular"   – 9:30–16:00 ET
            "pre"       – 4:00–9:30 ET
            "after"     – 16:00–20:00 ET
            "closed"    – outside all sessions
            "weekend"   – Saturday/Sunday
            "holiday"   – NYSE holiday
        """
        eastern = pytz.timezone("US/Eastern")
        now_et = datetime.now(eastern)

        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.schedule(start_date=now_et.date(), end_date=now_et.date())

        # --- Weekend ---
        if now_et.weekday() >= 5:
            return "weekend"

        # --- Holiday ---
        if schedule.empty:
            return "holiday"

        # --- Define session boundaries ---
        rth_start = now_et.replace(hour=9,  minute=30, second=0, microsecond=0)
        rth_end   = now_et.replace(hour=16, minute=0,  second=0, microsecond=0)

        pre_start = now_et.replace(hour=4,  minute=0,  second=0, microsecond=0)
        pre_end   = rth_start

        after_start = rth_end
        after_end   = now_et.replace(hour=20, minute=0, second=0, microsecond=0)

        # --- Regular Trading Hours ---
        if rth_start <= now_et <= rth_end:
            return "regular"

        # --- Pre-Market ---
        if pre_start <= now_et < pre_end:
            return "pre"

        # --- After-Hours ---
        if after_start < now_et <= after_end:
            return "after"

        # --- Fully Closed (20:00–4:00) ---
        return "closed"

    def set_market_data_type(self):
        session = self.get_market_session()

        if session == "regular":
            self.ib.reqMarketDataType(1)   # live
            logger.info("[QuoteManager] Using LIVE data (1) — regular hours")

        elif session in ("pre", "after"):
            self.ib.reqMarketDataType(1)   # frozen
            logger.info("[QuoteManager] Using LIVE data (1) — extended hours")

        else:  # closed, weekend, holiday
            self.ib.reqMarketDataType(3)   # delayed
            logger.info("[QuoteManager] Using DELAYED data (3) — market closed")
        
        return session

    # ---------------------------------------------------------
    # ✅ Synthetic Last Price
    # ---------------------------------------------------------
    def compute_last(self, ticker, session):
        last = clean_numeric(ticker.last)
        bid = clean_numeric(ticker.bid)
        ask = clean_numeric(ticker.ask)
        close = clean_numeric(ticker.close)
        
        # Prefer a real last if present 
        if last is not None:
            return last
        # Mid if both sides available
        if bid is not None and ask is not None:
            return (bid + ask) / 2
        if bid is not None:
            return bid
        if ask is not None:
            return ask
        
        # fallback: yesterday's close for options and stocks
        if session in ("pre", "after", "closed", "weekend", "holiday"):
            return close

        return None

    # ---------------------------------------------------------
    # ✅ Contract Builder (fixed Option constructor)
    # ---------------------------------------------------------
    def _make_contract(self, symbol, expiry=None, strike=None, right=None,
                       exchange="SMART", currency="USD"):

        # ✅ Option(symbol: str = '', lastTradeDateOrContractMonth: str = '',
        #       strike: float = 0.0, right: str = '', exchange: str = '',
        #       multiplier: str = '', currency: str = '', **kwargs)
        if expiry and strike and right:
            multiplier = 100.0
            return Option(symbol, expiry, float(strike), right, exchange, multiplier, currency)

        if symbol == "AAPL":
            return Stock(symbol, exchange, currency, primaryExchange="NASDAQ")    
        return Stock(symbol, exchange, currency)

    # ---------------------------------------------------------
    # ✅ Subscribe (with contract validation)
    # ---------------------------------------------------------
    def subscribe(self, symbol, expiry=None, strike=None, right=None):
        key = (symbol, expiry, strike, right)

        session = self.current_session

        if session is None:
            logger.warning(
                "[subscribe] current_session is None; did you forget to call "
                "set_market_data_type() before subscribe()?"
            )

        # ✅ Force correct market data type at subscription time
        if self.current_session in ("closed", "weekend", "holiday"):
            self.ib.reqMarketDataType(3)
            logger.info("[subscribe] Forcing DELAYED data (3) before reqMktData")
        else:
            self.ib.reqMarketDataType(1)
            logger.info("[subscribe] Forcing LIVE data (1) before reqMktData")

        # Don't trust stale tickers after cancel_all or reruns
        # ticker = self.tickers.get(key)

        # ✅ If ticker exists but session changed → force fresh subscription
        with self.lock:
            if key in self.tickers:
                old_session = getattr(self.tickers[key], "_session", None)

                if old_session != session:
                    logger.info(f"[subscribe] session changed {old_session} → {session}, refreshing ticker for {key}")
                    self.ib.cancelMktData(self.tickers[key])
                    del self.tickers[key]
                else:
                    logger.info(f"[subscribe] reuse ticker for {key} (session={session})")
                    return self.tickers[key]

            contract = self._make_contract(symbol, expiry, strike, right)
            logger.info(f"[subscribe] built contract={contract} for {key}")

            # only qualify for options
            if expiry and strike and right:
                logger.info(f"[subscribe] calling qualifyContracts for {key}")
                qualified = self.ib.qualifyContracts(contract)
                logger.info(f"[subscribe] qualified={qualified} for {key}")
                if not qualified:
                    logger.error(f"[subscribe] could NOT qualify contract for {key}")
                    return None

                contract = qualified[0]
                logger.info(f"[subscribe] using qualified contract={contract} for {key}")
            else:
                logger.info(f"[subscribe] qualifying stock contract for {key}")
                qualified = self.ib.qualifyContracts(contract)
                logger.info(f"[subscribe] stock qualified={qualified} for {key}")
                if qualified:
                    contract = qualified[0]

            # Stocks skip qualification entirely
            if expiry and strike and right:
                generic_ticks = "106" 
            else:
                generic_ticks = "165" 

            logger.info(f"[subscribe] calling reqMktData for {contract} - {key}")
            logger.info(f"[subscribe] generic_ticks={generic_ticks} for {key}")
            ticker = self.ib.reqMktData(
                contract,
                genericTickList=generic_ticks,
                snapshot=False
            )

            # Store the session used for this ticker
            ticker._session = session

            logger.info(f"[DEBUG] ticker._session={getattr(ticker, '_session', None)} current_session={session}")
            logger.info(f"[subscribe] reqMktData returned ticker={ticker} with ticker.last={ticker.last}, ticker.bid={ticker.bid}, ticker.ask={ticker.ask}, ticker.close={ticker.close} for {key}")

            self.tickers[key] = ticker
            return ticker

    # ---------------------------------------------------------
    # ✅ Main Quote Function (non‑freezing)
    # ---------------------------------------------------------
    def safe_get_quote(self, *args, **kwargs):
        try:
            return self.get_quote(*args, **kwargs)
        except Exception as e:
            logger.exception(f"[safe_get_quote] error: {e}")
            return {
                "last": None,
                "bid": None,
                "ask": None,
                "delta": None,
                "gamma": None,
                "vega": None,
                "theta": None,
                "iv": None,
                "timestamp": time.time()               
            }

    def get_quote(self, symbol, exchange="SMART", currency="USD",
                  expiry=None, strike=None, right=None, timeout=2.5):
        logger.info(f"[get_quote] START symbol={symbol}, expiry={expiry}, strike={strike}, right={right}")
        self.ensure_connected()
        logger.info(f"[get_quote] ensure_connected OK for {symbol}")
        logger.info(f"[get_quote] using IB instance id={id(self.ib)}, isConnected={self.ib.isConnected()}")

        # Get session and set market data type
        session = self.set_market_data_type()
        self.current_session = session
        logger.info(f"[get_quote] Request the right market data: session={session}")

        # Longer timeout for delayed data
        effective_timeout = 5 if session in ("closed", "weekend", "holiday") else timeout

        key = (symbol, expiry, strike, right)
        ticker = self.subscribe(symbol, expiry, strike, right)
        logger.info(f"[get_quote] subscribe returned ticker={ticker} for {symbol}")

        if ticker is None:
            logger.error(f"[get_quote] ticker is None for {key}")
            return None

        # ✅ Wait for IBKR to send *any* data
        start = time.time()
        while True:
            elapsed = time.time() - start

            logger.info(
                f"[DEBUG:get_quote] symbol={symbol} elapsed={elapsed:.2f}s "
                f"last={ticker.last} bid={ticker.bid} ask={ticker.ask} close={ticker.close} "
                f"mg={ticker.modelGreeks}"
            )

            if (
                (isinstance(ticker.last, (int, float)) and not math.isnan(ticker.last)) or
                (isinstance(ticker.close, (int, float)) and not math.isnan(ticker.close)) or
                (isinstance(ticker.bid, (int, float)) and not math.isnan(ticker.bid)) or
                (isinstance(ticker.ask, (int, float)) and not math.isnan(ticker.ask)) or
                ticker.modelGreeks is not None
            ):
                logger.info(
                f"[get_quote] data ready for {symbol}: "
                f"last={ticker.last}, bid={ticker.bid}, ask={ticker.ask}, mg={ticker.modelGreeks}"
                )
                break
            
            if elapsed >= effective_timeout:
                logger.warning(
                f"[get_quote] TIMEOUT for {symbol} after {elapsed:.2f}s: "
                f"last={ticker.last}, bid={ticker.bid}, ask={ticker.ask}, mg={ticker.modelGreeks}"
                )
                break

            self.ib.sleep(0.1)

        mg = ticker.modelGreeks
        synthetic_last = self.compute_last(ticker, session)

        quote = {
            "last": synthetic_last,
            "bid": ticker.bid,
            "ask": ticker.ask,
            "close": ticker.close,
            "delta": mg.delta if mg else None,
            "gamma": mg.gamma if mg else None,
            "vega": mg.vega if mg else None,
            "theta": mg.theta if mg else None,
            "iv": mg.impliedVol if mg else None,
            "timestamp": time.time()
        }

        self.cache[key] = quote
        return quote

    # ---------------------------------------------------------
    # ✅ Cancel Single Subscription
    # ---------------------------------------------------------
    def cancel(self, symbol, expiry=None, strike=None, right=None):
        key = (symbol, expiry, strike, right)
        if key in self.tickers:
            ticker = self.tickers[key]
            self.ib.cancelMktData(ticker)
            del self.tickers[key]

    # ---------------------------------------------------------
    # ✅ Cancel All Subscriptions (Streamlit rerun safe)
    # ---------------------------------------------------------
    def cancel_all(self):
        """
        Safely cancel all known market data subscriptions.
        This should NEVER crash or poison future subscriptions.
        """
        if not self.ib or not self.ib.isConnected():
            self.tickers.clear()
            return

        for key, ticker in list(self.tickers.items()):
            try:
                if ticker is not None:
                    self.ib.cancelMktData(ticker)
            except Exception as e:
                logger.warning(f"[cancel_all] Failed to cancel {key}: {e}")
            finally:
                # Always remove our references so we don't reuse stale tickers
                self.tickers.pop(key, None)
        
        logger.info(f"[cancel_all] All known subscriptions removed from QuoteManager.")