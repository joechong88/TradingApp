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
import concurrent.futures
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
        self.version = 0
        logger.info(f"[QuoteManager.__init__] self.ib id={id(self.ib)}")

    # ---------------------------------------------------------
    # ✅ Hard Reset (for Streamlit Refresh Button)
    # ---------------------------------------------------------
    def reset(self):
        """
        Fully reset the QuoteManager:
        - Cancel all IBKR subscriptions
        - Clear cached tickers
        - Clear internal quote cache
        - Reconnect IBKR cleanly
        - Increment version to invalidate all cached quotes
        """
        logger.info("[QuoteManager.reset] Resetting quote manager...")

        # Cancel all subscriptions
        try:
            for key, ticker in list(self.tickers.items()):
                try:
                    self.ib.cancelMktData(ticker)
                except Exception as e:
                    logger.warning(f"[reset] Failed to cancel ticker {key}: {e}")
        except Exception as e:
            logger.error(f"[reset] Error during cancel_all: {e}")

        # Clear internal state
        self.tickers = {}
        self.cache = {}
        self.current_session = None

        # Disconnect IBKR
        try:
            if self.ib is not None:
                self.ib.disconnect()
        except Exception:
            pass

        # Force new IB connection
        self.ib = None
        self.ensure_connected()

        # Increment version to invalidate all cached quotes
        self.version += 1

        logger.info(f"[QuoteManager.reset] Completed. version={self.version}")

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

    def get_status(self):
        """Returns (status_text, color_icon, session_name)"""
        if not self.ib:
            return "Disconnected", "🔴", "N/A"
        
        if self.ib.isConnected():
            session = self.get_market_session()
            icon = "🟢" if session == "regular" else "🔵"
            return "Connected", icon, session
        
        return "Disconnected", "⚪", "N/A"

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
        """
        Calculates the most accurate price for a contract based on the session state.
        Prioritizes delayed trade data (14.65) over the session close (14.58).
        """
        # 1. Prioritize 'Last' Trade (Delayed vs Live)
        # If the session is closed, we MUST check delayedLast first to get the 14.65 value
        d_last = clean_numeric(getattr(ticker, 'delayedLast', None))
        r_last = clean_numeric(ticker.last)
        r_close = clean_numeric(ticker.close)
        d_close = clean_numeric(getattr(ticker, 'delayedClose', None))
        
        # --- DEBUG PRINT ---
        logger.info(f"[DEBUG:compute_last] {ticker.contract.localSymbol} | "
                    f"r_last: {r_last} | d_last: {d_last} | "
                    f"r_close: {r_close} | d_close: {d_close}")

        if session in ("closed", "weekend", "holiday"):
            if d_last: return d_last  # Captured from Tick ID 68
            if r_last: return r_last
        else:
            if r_last: return r_last
            if d_last: return d_last
            
        # 2. Check Bid/Ask Midpoint (Regular or Delayed)
        bid = clean_numeric(ticker.bid) or clean_numeric(getattr(ticker, 'delayedBid', None))
        ask = clean_numeric(ticker.ask) or clean_numeric(getattr(ticker, 'delayedAsk', None))
        
        if bid and ask and bid > 0 and ask > 0:
            mid = (bid + ask) / 2
            logger.info(f"[DEBUG:compute_last] Using Midpoint: {mid}")
            return mid

        # 3. Final Fallback: Model Price (The 'Fair Value' from Greeks)
        # If the market is totally illiquid, the Model Price is better than None
        # In closed sessions, 'modelGreeks' is often None while 'lastGreeks' is populated
        if ticker.contract.secType == 'OPT':
            mg = ticker.modelGreeks or getattr(ticker, 'lastGreeks', None) or getattr(ticker, 'bidAskGreeks', None)
            if mg:
                opt_price = clean_numeric(getattr(mg, 'optPrice', None))
                if opt_price:
                    return opt_price

        # 4. Fallback to Close (Regular or Delayed)
        final_fallback = r_close or d_close
        if final_fallback:
            logger.info(f"[DEBUG:compute_last] Falling back to Close: {final_fallback}")        
            return final_fallback

        return None

    # ---------------------------------------------------------
    # ✅ Contract Builder (fixed Option constructor)
    # ---------------------------------------------------------
    def _make_contract(self, symbol, expiry=None, strike=None, right=None, exchange="SMART", currency="USD"):

        # ✅ Option(symbol: str = '', lastTradeDateOrContractMonth: str = '',
        #       strike: float = 0.0, right: str = '', exchange: str = '',
        #       multiplier: str = '', currency: str = '', **kwargs)
        if expiry and strike and right:
            multiplier = "100"
            return Option(symbol, expiry, float(strike), right, exchange, multiplier, currency)

        return Stock(symbol, exchange, currency)

    # ---------------------------------------------------------
    # ✅ Same , time-out protected version of qualify
    # ---------------------------------------------------------
    def safe_qualify(self, contract, timeout=2.0): # Increased to 5s for delayed data
        """
        Streamlit-safe qualification. 
        Ensures the async call happens on the correct event loop.
        """
        if not self.ib or not self.ib.isConnected():
            logger.error("[safe_qualify] IB not connected")
            return None

        try:
            # Instead of run_coroutine_threadsafe, use the built-in ib.run
            # to process the qualifyContracts coroutine.
            coro = self.ib.qualifyContractsAsync(contract)
            
            # This blocks the current thread but allows the IB loop to process events
            result = self.ib.run(asyncio.wait_for(coro, timeout=timeout))
            
            if result:
                return result[0]
            return None
        except Exception as e:
            # Logs as 'Qualification failed for TSLA: [Error message]'
            logger.warning(f"[safe_qualify] Qualification failed for {contract.symbol}: {e}")
            return None

    # ---------------------------------------------------------
    # ✅ Subscribe (with contract validation)
    # ---------------------------------------------------------
    def subscribe(self, symbol, expiry=None, strike=None, right=None, session=None):
        key = (symbol, expiry, strike, right, self.version)
        # Use the passed session if available, otherwise fallback to class state
        effective_session = session or self.current_session

        if effective_session is None:
            logger.warning(
                "[subscribe] current_session is None; did you forget to call "
                "set_market_data_type() before subscribe()?"
            )

        # ✅ Force correct market data type at subscription time
        if effective_session in ("closed", "weekend", "holiday"):
            self.ib.reqMarketDataType(3)
            logger.info("[subscribe] Forcing DELAYED data (3) before reqMktData")
        else:
            self.ib.reqMarketDataType(1)
            logger.info("[subscribe] Forcing LIVE data (1) before reqMktData")

        # ✅ If ticker exists but session changed → force fresh subscription
        with self.lock:
            if key in self.tickers:
                old_session = getattr(self.tickers[key], "_session", None)

                if old_session != effective_session:
                    logger.info(f"[subscribe] session changed {old_session} → {effective_session}, refreshing ticker for {key}")
                    self.ib.cancelMktData(self.tickers[key])
                    del self.tickers[key]
                else:
                    logger.info(f"[subscribe] reuse ticker for {key} (session={effective_session})")
                    return self.tickers[key]

            # 1. Start with SMART
            contract = self._make_contract(symbol, expiry, strike, right)
            logger.info(f"[subscribe] built contract={contract} for {key}")
            logger.info(f"[subscribe] Attempting qualification (SMART) for {symbol}")
            qualified = self.safe_qualify(contract)

            # 2. Fallback logic for options if SMART fails
            if not qualified and expiry:
                fallbacks = ["BOX", "CBOE", "AMEX"]
                for exch in fallbacks:
                    logger.info(f"[subscribe] SMART failed. Retrying with {exch} for {symbol}...")
                    contract = self._make_contract(symbol, expiry, strike, right, exchange=exch)
                    qualified = self.safe_qualify(contract, timeout=2.0) # Shorter timeout for retries
                    if qualified:
                        logger.info(f"[subscribe] Successfully qualified via {exch}")
                        break
                    self.ib.sleep(0.1)

            if not qualified:
                logger.error(f"[subscribe] All exchanges failed for {key}")
                return None
            
            # At this point, qualified is definitely a single Contract object (not a list)
            contract = qualified

            # Set tick list based on asset type
            generic_ticks = "106" if expiry else "165"

            logger.info(f"[subscribe] calling reqMktData for {contract} - {key}")
            logger.info(f"[subscribe] generic_ticks={generic_ticks} for {key}")
            ticker = self.ib.reqMktData(
                contract,
                genericTickList=generic_ticks,
                snapshot=False
            )

            # Store the session used for this ticker
            ticker._session = effective_session

            logger.info(f"[DEBUG] ticker._session={ticker._session} session_context={effective_session}")
            logger.info(f"[subscribe] reqMktData returned ticker={ticker} with ticker.last={ticker.last}, ticker.bid={ticker.bid}, ticker.ask={ticker.ask}, ticker.close={ticker.close} for {key}")

            self.tickers[key] = ticker
            return ticker

    # ---------------------------------------------------------
    # ✅ Main Quote Function (non‑freezing)
    # ---------------------------------------------------------
    def safe_get_quote(self, *args, **kwargs):
        default_quote = {
            "last": None, "bid": None, "ask": None, "close": None, 
            "delta": None, "gamma": None, "vega": None, "theta": None, "iv": None, 
            "timestamp": time.time()
        }

        try:
            kwargs["version"] = self.version
            res = self.get_quote(*args, **kwargs)
            return res if res is not None else default_quote
        except Exception as e:
            logger.exception(f"[safe_get_quote] error: {e}")
            return default_quote

    def get_quote(self, symbol, exchange="SMART", currency="USD",
                  expiry=None, strike=None, right=None, timeout=2.5, version=0):
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

        key = (symbol, expiry, strike, right, self.version)
        ticker = self.subscribe(symbol, expiry, strike, right)
        logger.info(f"[get_quote] subscribe returned ticker={ticker} for {symbol}")

        if ticker is None:
            logger.error(f"[get_quote] ticker is None for {key}")
            return None

        # ✅ Wait for IBKR to send *any* data
        start = time.time()
        while True:
            elapsed = time.time() - start

            # Use your logic to see if we have ANY valid price yet
            synthetic_last = self.compute_last(ticker, self.current_session)

            # Check for Greeks (Model, Last, Bid, or Ask versions)
            mg_source = "None"
            mg = None

            logger.info(
                f"[DEBUG:get_quote] symbol={symbol} elapsed={elapsed:.2f}s "
                f"L={ticker.last} dL={getattr(ticker, 'delayedLast', 'nan')} " # Added dL
                f"B={ticker.bid} A={ticker.ask} C={ticker.close} "
                f"mg_src={mg_source}"
            )

            if ticker.modelGreeks:
                mg, mg_source = ticker.modelGreeks, "modelGreeks"
            elif getattr(ticker, 'lastGreeks', None):
                mg, mg_source = ticker.lastGreeks, "lastGreeks"
            elif getattr(ticker, 'bidAskGreeks', None):
                mg, mg_source = ticker.bidAskGreeks, "bidAskGreeks"

            has_price = synthetic_last is not None
            has_greeks = mg is not None and not math.isnan(getattr(mg, 'impliedVol', float('nan')))

            logger.info(f"[DEBUG:get_quote loop] {symbol} | Price Found: {has_price} ({synthetic_last}) | "
                        f"Greeks Source: {mg_source} | IV: {getattr(mg, 'impliedVol', 'N/A')}")

            # Only break if we have BOTH, or if we've timed out
            is_option = (ticker.contract.secType == 'OPT')
            if (has_price and (not is_option or has_greeks)):
                logger.info(f"[get_quote] Full data ready for {symbol}")
                break
            
            if elapsed >= effective_timeout:
                logger.warning(
                f"[get_quote] TIMEOUT for {symbol} after {elapsed:.2f}s: "
                f"last={ticker.last}, bid={ticker.bid}, ask={ticker.ask}, mg={ticker.modelGreeks}"
                )
                break

            self.ib.sleep(0.05)

        quote = {
            "last": synthetic_last,
            "bid": clean_numeric(ticker.bid) or clean_numeric(getattr(ticker, 'delayedBid', None)), 
            "ask": clean_numeric(ticker.ask) or clean_numeric(getattr(ticker, 'delayedAsk', None)),
            "close": clean_numeric(ticker.close) or clean_numeric(getattr(ticker, 'delayedClose', None)),
            "delta": getattr(mg, 'delta', None) if mg else None,
            "gamma": getattr(mg, 'gamma', None) if mg else None,
            "vega": getattr(mg, 'vega', None) if mg else None,
            "theta": getattr(mg, 'theta', None) if mg else None,
            "iv": getattr(mg, 'impliedVol', None) if mg else None,
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