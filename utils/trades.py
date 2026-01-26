import asyncio
import sys
import os

# 1. Get the absolute path to the directory two levels up from this file
# This takes you from streamlit_app/pages/ -> streamlit_app/ -> Root
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))

# 2. Add that root path to sys.path so 'db' and 'utils' can be found
if root_path not in sys.path:
    sys.path.insert(0, root_path)

import pandas as pd
import logging
import streamlit as st
import pytz
import time
import threading
from typing import Dict, List
from sqlalchemy.orm import joinedload
from sqlalchemy import desc, update
from db.models import SessionLocal, Trade, TradeGroup, Leg, Transaction
from datetime import datetime
from utils.logger import get_logger
from utils.quote_manager import QuoteManager
from utils.config_loader import load_config, save_config_local

@st.cache_resource(show_spinner=False)
def get_qm() -> QuoteManager:
    """
    Return a singleton QuoteManager per Streamlit session.
    QuoteManager itself handles reconnection and subscriptions.
    """
    return QuoteManager()

# --- Initiate logging
logger = get_logger(__name__)

def calculate_pnl(data, live_price: float = None) -> tuple:
    """
    Unified P&L calculator for both Trade objects and DataFrame rows.
    Handles Stocks (1x) and Options (100x).
    Returns (net_pnl, pnl_pct)
    """
    # 0. Load fresh config to catch updates from the Settings page
    config = load_config()
    stock_pnl_target = config["targets"]["stock_pnl_target"]

    # 1. Handle Input Type (Object vs Dictionary/Row)
    # This allows the function to work with trade_obj.attribute or row['column']
    if hasattr(data, "__getitem__"):  # It's a dict or pandas row
        entry_price = data.get("entry_price")
        exit_price = data.get("exit_price")
        units = data.get("units")
        entry_comm = data.get("entry_commissions", 0) or 0
        exit_comm = data.get("exit_commissions", 0) or 0
        strategy = str(data.get("strategy", "")).lower().strip()
        has_option_attrs = data.get("strikeprice") and data.get("expiry_dt")
    else:  # It's a Trade class object
        entry_price = data.entry_price
        exit_price = data.exit_price
        units = data.units
        entry_comm = data.entry_commissions or 0
        exit_comm = data.exit_commissions or 0
        strategy = str(getattr(data, "strategy", "")).lower().strip()
        has_option_attrs = getattr(data, "strikeprice", None) and getattr(data, "expiry_dt", None)

    # 2. Determine Exit/Live Price
    price_out = live_price if live_price is not None else exit_price
    
    if price_out is None or entry_price is None:
        return 0.0, 0.0 # return 2 zeros instead of one

    # 3. Determine Multiplier
    # Logic: If specifically 'long'/'short' -> Stock. 
    # Otherwise, if it has option attributes -> Option.
    is_stock = strategy in ["long", "short"]
    if is_stock:
        multiplier = 1
    elif has_option_attrs or strategy not in ["", "none"]:
        multiplier = 100
    else:
        multiplier = 1  # Default fallback to Stock

    # 4. Final Calculation
    gross_pnl = (price_out - entry_price) * units * multiplier
    net_pnl = gross_pnl - entry_comm - exit_comm

    # 5. Calculate P&L %
    pnl_pct = 0.0
    if is_stock:
        # Stock Rule: progress towards the daily target saved in config.toml
        pnl_pct = (net_pnl / stock_pnl_target) * 100
    else:
        # Option Rule: Net P&L / Initial Cost
        # If units is negative, it means CSP or CC, hence need to flip the sign to calculate
        initial_premium = abs(entry_price * units) * 100
        if initial_premium != 0:    # safety guide
            pnl_pct = (net_pnl / initial_premium) * 100

    return net_pnl, pnl_pct

def calc_pdh_pdl(df: pd.DataFrame) -> Dict[str, float]:
    if df.empty:
        return {"PDH": None, "PDL": None}
    dates = pd.to_datetime(df.index).date
    last_day = dates[-1]
    prev_mask = dates != last_day
    prev_df = df[prev_mask] if prev_mask.any() else df.iloc[:-1]
    if prev_df.empty:
        return {"PDH": None, "PDL": None}
    return {"PDH": float(prev_df["High"].max()), "PDL": float(prev_df["Low"].min())}

def safe_option_price(opt_quote: dict, trade) -> float | None:
    """
    Return option last price if available, otherwise fallback to stored exit/entry or cached close.
    """
    last = opt_quote.get("last")
    if last is not None:
        return last

    # Fallback: use exit_price if trade is closed, else entry_price as proxy
    if trade.exit_price:
        return trade.exit_price
    return trade.entry_price

# Utility function to built the trade's label to be populated in the Close Trade selection box  
def build_trade_label(row):
    # Base: symbol + strategy
    label = f"{row['symbol']} — {row['strategy']}"

    # If it's an option, append expiry + strike
    if row.get("expiry_dt") and row.get("strikeprice"):
        # Determine the right (C or P) based on strategy
        strategy_lower = row["strategy"].lower()
        right = "P" if strategy_lower.startswith("csp") else "C"

        expiry = row["expiry_dt"]
        strike = row["strikeprice"]
        label = f"{row['symbol']} {expiry} {strike}{right} — {row['strategy']}"

    return label

def trades_to_df(trades: List[Trade], live: bool = True, qm=None) -> pd.DataFrame:
    """
    Convert a list of Trade objects into a Pandas DataFrame.
    - live=True: fetch IBKR live quotes for open trades.
    - live=False: skip IBKR calls, use only stored DB values.
    Ensures all expected columns exist, even if trades is empty.
    """
    rows = []
    for t in trades:
        # Default values
        option_last = option_bid = option_ask = None
        stock_last = stock_bid = stock_ask = None

        # Determine live price if trade  is open
        live_price = None
        itm_status = None

        if live and t.is_open:
            if qm is not None:
                if t.strikeprice and t.expiry_dt:
                    #Option trade -> use option_last
                    right = "P" if t.strategy.lower().startswith("csp") else "C"
                    expiry_dt = str(t.expiry_dt)
                    strikeprice = float(t.strikeprice)

                    start = time.time()
                    logger.info("Fetching live option quote for %s %s %s%s", t.symbol, expiry_dt, strikeprice, right)
                    try:
                        opt_quote = qm.safe_get_quote(
                            symbol      = t.symbol,
                            exchange    = "SMART",
                            currency    = "USD",
                            expiry      = expiry_dt,
                            strike      = strikeprice,
                            right       = right
                        )
                        logger.debug("get_quote() took %.2f seconds", time.time()-start)

                        if opt_quote:
                            option_last = opt_quote.get("last")
                            live_price = option_last
                            logger.debug("Received option quote for %s %s %s%s: %s", t.symbol, expiry_dt, strikeprice, right, option_last)
                        else:
                            option_last = None
                            logger.warning("No option quote for %s %s %s%s (opt_quote is None)", t.symbol, expiry_dt, strikeprice, right)

                    except Exception as e:
                        logger.error("Option quote failed for %s: %s", t.symbol, e)

                    # also fetch underlying stock quote
                    start = time.time()
                    logger.debug("Fetching live stock quote (in options) for %s", t.symbol)
                    try:                    
                        stock_quote = qm.safe_get_quote(
                            symbol      = t.symbol
                        )
                        logger.debug("get_quote() took %.2f seconds", time.time()-start)

                        if stock_quote:
                            stock_last = stock_quote.get("last")
                            stock_bid = stock_quote.get("bid")
                            stock_ask = stock_quote.get("ask")
                            logger.debug("Received stock quote (in options) for %s: %s", t.symbol, stock_last)
                        else:
                            stock_last = stock_bid = stock_ask = None
                    except Exception as e:
                        logger.error("Stock quote failed for %s: %s", t.symbol, e)

                    # ITM/OTM logic
                    if stock_last is not None:
                        if right == "P":
                            itm_status = "ITM" if stock_last < t.strikeprice else "OTM"
                        else: # Call
                            itm_status = "ITM" if stock_last > t.strikeprice else "OTM"
                else:
                    # Stock trade -> use stock_last
                    start = time.time()
                    logger.debug("Fetching live stock quote for %s", t.symbol)
                    try:
                        stock_quote = qm.safe_get_quote(
                            symbol      = t.symbol
                        )
                        logger.debug("get_quote() took %.2f seconds", time.time()-start)
                        stock_last = stock_quote.get("last")
                        stock_bid = stock_quote.get("bid")
                        stock_ask = stock_quote.get("ask")
                        live_price = stock_last
                        logger.debug("Received stock quote for %s: %s", t.symbol, stock_last)
                    except Exception as e:
                        logger.error("Stock quote failed for %s: %s", t.symbol, e)

        # Build row
        net_pnl, pnl_pct = calculate_pnl(t, live_price=live_price)
        rows.append({
            "id": t.id,
            "symbol": t.symbol,
            "strategy": t.strategy,
            "units": t.units,
            "strikeprice": t.strikeprice,
            "expiry_dt": str(t.expiry_dt) if t.expiry_dt else None,
            "entry_price": t.entry_price,
            "expected_rr": t.expected_rr,
            "entry_dt": t.entry_dt,
            "entry_commissions": t.entry_commissions,
            "is_open": t.is_open,
            "exit_price": t.exit_price,
            "exit_dt": t.exit_dt,
            "exit_commissions": t.exit_commissions,
            "notes": t.notes,
            "option_last": option_last,
            "option_bid": option_bid,
            "option_ask": option_ask,
            "stock_last": stock_last,
            "stock_bid": stock_bid,
            "stock_ask": stock_ask,
            "itm_status": itm_status,
            "live_price": live_price,
            "pnl": net_pnl,
            "pnl_pct": pnl_pct
        })

    # Define all expected columns' header
    columns = [
        "id", "symbol", "strategy", "units", "strikeprice", "expiry_dt",
        "entry_price", "expected_rr", "entry_dt", "entry_commissions",
        "is_open", "exit_price", "exit_dt", "exit_commissions", "notes", 
        "option_last", "option_bid", "option_ask", "stock_last", "stock_bid", "stock_ask",
        "itm_status", "live_price", "pnl", "pnl_pct"
    ]

    return pd.DataFrame(rows, columns=columns)

def compute_trade_duration(df, entry_col="entry_dt", exit_col="exit_dt"):
    """
    Adds a 'duration' column showing the time spent in the trade
    as a human-readable string (Xd Yh Zm).
    """
    # Ensure datetime
    df[entry_col] = pd.to_datetime(df[entry_col])
    df[exit_col] = pd.to_datetime(df[exit_col])

    durations = []

    for entry, exit_ in zip(df[entry_col], df[exit_col]):
        delta = exit_ - entry

        total_minutes = int(delta.total_seconds() // 60)
        days = total_minutes // (24 * 60)
        hours = (total_minutes % (24 * 60)) // 60
        minutes = total_minutes % 60

        # Build readable string
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or (days == 0 and hours == 0):
            parts.append(f"{minutes}m")

        durations.append(" ".join(parts))

    df["duration"] = durations
    return df

def calculate_strategy_cost(legs, contract_multiplier=100):
    """
    Calculates the total net cost (basis) for a group of legs.
    Positive result = Net Debit (You paid money)
    Negative result = Net Credit (You received money)
    This function is no longer used, replaced by calculate_comprehensive_pnl
    """
    gross_basis = 0.0
    net_basis = 0.0
    comm = 0.0

    for leg in legs:
        # Financial Value = (Price * Multiplier * Quantity)
        price = leg.entry_price or 0.0
        qty = abs(leg.quantity or 0)    # Use absolute 
        mult = contract_multiplier or 100

        # Determine direction based on side
        # STO/Sell should result in negative cash flow (credit)
        side = leg.side.upper() if leg.side else ""
        side_mult = -1 if side in ["STO", "SELL"] else 1

        leg_cash_value = (price * mult * qty * side_mult)
        
        gross_basis += leg_cash_value
        comm += (leg.entry_commission or 0.0)
    
    # Total out-of-pocket or into-pocket
    is_debit = gross_basis > 0
    direction_label = "Net Debit" if is_debit else "Net Credit"
    net_basis = (gross_basis - comm) if is_debit else (gross_basis + comm)

    return {
        "raw_basis": gross_basis,
        "is_debit": is_debit,
        "label": direction_label,
        "formatted_abs": f"${abs(net_basis):,.2f}", # Added comma for thousands
        "commissions": comm
    }

def get_all_open_positions(qm=None):
    """
    Centralized fetcher for both Flat and Complex trades.
    Returns a tuple: (list of flat_trades, list of complex_groups)
    """
    with SessionLocal() as db:
        # 1. Fetch Flat trades
        flat_trades = (
            db.query(Trade)
            .filter(Trade.is_open == True)
            .order_by(desc(Trade.entry_dt))
            .all()
        )

        # 2. Fetch Complex trades with Eager Loading
        # We load legs and their transactions to prevent detached session errors in Streamlit
        complex_groups = (
            db.query(TradeGroup)
            .options(
                joinedload(TradeGroup.legs).joinedload(Leg.transactions)
            )
            .filter(TradeGroup.status == "Open")
            .all()
        )
    
    # --- DEBUG 1: Verify SQLAlchemy Results ---
        logger.debug(f"\n--- DATABASE FETCH DEBUG ---")
        for group in complex_groups:
            leg_statuses = [l.status for l in group.legs]
            logger.debug(f"Group ID {group.id}: Total Legs Found: {len(group.legs)} | Statuses: {leg_statuses}")

    # --- Convert Flat Trades to enriched DF ---
    flat_df = trades_to_df(flat_trades, live=True, qm=qm)
    flat_df2 = enrich_with_expiry(flat_df)
        
    # --- Convert Complex Trades to Enriched DF ---
    # For complex trades, we usually want the 'soonest' expiry to represent the group
    logger.debug(f"Passing {len(complex_groups)} groups to complex_groups_to_df...")
    complex_df = complex_groups_to_df(complex_groups, live=True, qm=qm)
    if not complex_df.empty:
        first_group_legs = complex_df.iloc[0]['legs']
        logger.debug(f"DataFrame Row 0 Legs Count: {len(first_group_legs)}")
    complex_df = enrich_with_expiry(complex_df)

    return flat_df2, complex_df

def enrich_with_expiry(df: pd.DataFrame) -> pd.DataFrame:
    """Applies your specific expiry and DTE logic to a DataFrame."""
    if df.empty or "expiry_dt" not in df.columns:
        return df

    # Your logic incorporated here:
    df["expiry_date"] = pd.to_datetime(df["expiry_dt"], format="%Y%m%d", errors="coerce")
    eastern = pytz.timezone("US/Eastern")
    
    # Use UTC now then convert to Eastern for comparison
    today_et = pd.Timestamp(datetime.now(eastern).date())
    df["days_to_expiry"] = (df["expiry_date"] - today_et).dt.days.clip(lower=0)
    
    return df

def complex_groups_to_df(groups: List[TradeGroup], live: bool = True, qm=None) -> pd.DataFrame:
    """
    Mirror of trades_to_df but for TradeGroup objects.
    Fetches live quotes for each leg and calculates total strategy value.
    """
    rows = []
    for g in groups:
        all_legs = g.legs 
        if not all_legs:
            continue
            
        total_current_value = 0.0
        live_data_available = False
        enriched_legs = []

        # Process each leg similar to how trades_to_df processes a single trade
        for l in all_legs:
            leg_last = None
            if live and qm is not None and l.status == "Active":
                try:
                    # Option Quote logic
                    if l.strikeprice and l.expiry_dt:
                        quote = qm.safe_get_quote(
                            symbol=l.symbol,
                            expiry=str(l.expiry_dt),
                            strike=float(l.strikeprice),
                            right=l.option_type
                        )
                        if quote:
                            leg_last = quote.get("last") or quote.get("close")
                            # Calculate contribution to strategy net value
                            # Long = Positive Value, Short = Negative Value (Liability)
                            multiplier = 1 if l.side == "Long" else -1
                            total_current_value += (leg_last * l.quantity * multiplier * 100)
                            live_data_available = True
                except Exception as e:
                    logger.error(f"Quote failed for leg {l.id}: {e}")

            # Attach the live price to the leg object temporarily for the UI
            l.live_price = leg_last
            enriched_legs.append(l)

        # Build the group row using all_legs for metadata
        # We find the first active leg for the ticker/expiry display, fallback to first leg
        primary_leg = next((l for l in enriched_legs if l.status == "Active"), enriched_legs[0])

        # Build the group row
        rows.append({
            "group_id": g.id,
            "strategy": g.strategy_name,
            "symbol": primary_leg.symbol,
            "expiry_dt": min([l.expiry_dt for l in enriched_legs if l.status == "Active" and l.expiry_dt], default=None),
            "legs": tuple(enriched_legs), # Using tuple to avoid Streamlit hashing errors
            "notes": g.notes,
            "live_value": total_current_value if live_data_available else None,
            "live_available": live_data_available
        })

    return pd.DataFrame(rows)

def execute_roll_short_call(group_id, old_leg_id, exit_price, exit_comm, new_params):
    """
    Handles the atomic transaction of closing an old leg and opening a new one.
    """
    logger.debug(f"[execute_roll_short_call] Entering the function with params: {new_params}")
    exec_dt = new_params.get('execution_dt')

    with SessionLocal() as db:
        logger.debug(f"[execute_roll_short_call] Initializing DB session")
        try:
            # 1. Fetch the old leg
            old_leg = db.get(Leg, old_leg_id)
            if not old_leg:
                return False, "Old leg not found."

            # 2. Close the Old Leg
            old_leg.status = "Rolled"
            old_leg.exit_date = exec_dt
            old_leg.exit_price = exit_price
            old_leg.exit_commission = exit_comm

            # 3. Record BTC (Buy to Close) Transaction
            btc_tx = Transaction(
                leg_id=old_leg.id,
                action="BTC",
                quantity=old_leg.quantity,
                price=exit_price,
                commission=exit_comm,
                timestamp=exec_dt,
                notes=f"Rolled to {new_params['expiry_dt']} @ {new_params['strikeprice']}"
            )
            db.add(btc_tx)
            logger.debug(f"Adding Transaction record: {btc_tx}")

            # 4. Create New Leg
            new_leg = Leg(
                group_id=group_id,
                symbol=old_leg.symbol,
                side=old_leg.side,
                quantity=old_leg.quantity,
                status="Active",
                option_type=old_leg.option_type,
                strikeprice=new_params['strikeprice'],
                expiry_dt=new_params['expiry_dt'],
                entry_date=exec_dt,
                entry_price=new_params['entry_price'],
                entry_commission=new_params['entry_comm']
            )
            db.add(new_leg)
            logger.debug(f"Adding New Leg record: {new_leg}")
            
            # Flush to get the new_leg.id for the next transaction record
            db.flush()

            # 5. Record STO (Sell to Open) Transaction
            sto_tx = Transaction(
                leg_id=new_leg.id,
                action="STO",
                quantity=new_leg.quantity,
                price=new_params['entry_price'],
                commission=new_params['entry_comm'],
                timestamp=exec_dt,
                notes=f"Rolled from leg ID {old_leg_id}"
            )
            db.add(sto_tx)
            logger.debug(f"Adding Transaction record: {sto_tx}")

            db.commit()
            return True, "Roll successful"
        except Exception as e:
            st.error(f"[execute_roll_short_call] Database error: {e}")
            logger.error(f"[execute_roll_short_call] Database error: {e}")
            db.rollback()
            return False, str(e)

def get_group_realized_pnl(group_id):
    """
    Calculates the total cash flow (Realized P&L + Entry Costs) 
    for all legs within a specific group.
    """
    with SessionLocal() as db:
        legs = db.query(Leg).filter(Leg.group_id == group_id).all()
        
        total_cash_flow = 0.0
        
        for leg in legs:
            # 1. Add Entry Cash Flow (Credit/Debit)
            # Short (-2) @ 5.19 = +1038.00 (Cash In)
            # Long (2) @ 20.94 = -4188.00 (Cash Out)
            entry_flow = (leg.quantity * leg.entry_price * 100 * -1) - leg.entry_commission
            total_cash_flow += entry_flow
            
            # 2. Add Exit Cash Flow (if it exists)
            if leg.exit_price is not None:
                # Close Short (-2) @ 8.70 = -1740.00 (Cash Out)
                exit_flow = (leg.quantity * leg.exit_price * 100) - leg.exit_commission
                total_cash_flow += exit_flow
                
        return total_cash_flow

def calculate_comprehensive_pnl(group_id, active_legs_data=None):
    """
    Calculates P&L for a group by summing all historical cash flows 
    and adding the current liquidation value of active legs.
    
    active_legs_data: A list of dicts/objects containing current market prices:
                      [{'leg_id': 19, 'live_price': 8.50}, ...]
    """
    #logger.info(f"\n--- DEBUG P&L START (Group ID: {group_id}) ---")
    with SessionLocal() as db:
        # 1. Fetch all legs for this group (Active, Rolled, and Closed)
        legs = db.query(Leg).filter(Leg.group_id == group_id).all()
        
        # Sort legs by entry_date to find the initial trade
        legs_sorted = sorted(legs, key=lambda x: x.entry_date)

        # Initial debit (the baseline) for calendar spread
        initial_entry_debit = 0.0
        total_realized_cash = 0.0
        total_liquidation_value = 0.0
        total_comm = 0.0

        first_entry_time = legs_sorted[0].entry_date if legs_sorted else None

        # total realized cash (including all rolls)
        for leg in legs:
            # 1. INITIAL ENTRY IMPACT (Determines if the trade started as Credit or Debit)
            # Short (+ cash), Long (- cash)
            entry_cash = (leg.quantity * leg.entry_price * 100 * -1)
            total_realized_cash += entry_cash

            # track commissions separately
            total_comm += leg.entry_commission
            total_realized_cash -= leg.entry_commission

            if leg.entry_date == first_entry_time:    
                initial_entry_debit += (entry_cash - leg.entry_commission) 

            # 2. CLOSED/ROLLED LEGS: Exit cash impact, Fully realized
            # Logic for ROLLED/CLOSED legs
            if leg.status in ["Rolled", "Closed"]:
                # Closing Short is -, Closing Long is +
                exit_cash = (leg.quantity * leg.exit_price * 100)
                total_realized_cash += exit_cash

                total_comm += leg.exit_commission
                total_realized_cash -= leg.exit_commission

                # only use for logging purposese
                closed_leg_comm = leg.entry_commission + leg.exit_commission
                closed_leg_pnl = exit_cash + entry_cash
                logger.info(f"LEG ID: {leg.id} | {leg.symbol} {leg.expiry_dt} {leg.strikeprice}{leg.option_type} | Qty: {leg.quantity}")
                logger.info(f"  > Realized: Entry ${entry_cash:,.2f} | Exit ${exit_cash:,.2f} | Comms ${closed_leg_comm:,.2f} | P&L ${closed_leg_pnl:,.2f} | Status: {leg.status}")

            # Logic for ACTIVE legs
            elif leg.status == "Active" and active_legs_data:
                l_data = next((x for x in active_legs_data if x['leg_id'] == leg.id), None)
                if l_data:
                    # 2. Calculate the CURRENT MARKET VALUE (Cost to liquidate)
                    # Short (-2) @ 0.50 Mark -> -$100 (It costs $100 to exit)
                    # Long (2) @ 0.10 Mark -> +$20 (We get $20 back)
                    leg_market_value = (leg.quantity * l_data['live_price'] * 100)
                    logger.info(f"  > CURRENT MARKET VALUE TO LIQUIDATE: (Mark {l_data['live_price']}) * Qty {leg.quantity} = {leg_market_value:,.2f}")
                
                    # 3. UNREALIZED is the difference between what we got and what it costs now
                    # This is mathematically identical to: (Live - Entry) * Qty * 100
                    total_liquidation_value += leg_market_value
                    logger.info(f"LEG ID: {leg.id} | {leg.symbol} {leg.expiry_dt} {leg.strikeprice}{leg.option_type} | Qty: {leg.quantity}")
                    logger.info(f"  > UNREALIZED: (Mark {l_data['live_price']} - Entry {leg.entry_price}) * Qty {leg.quantity} = {leg_market_value:,.2f}")
                        
        logger.info(f"--- SUMMARY ---")
        logger.info(f"Initial Baseline: {initial_entry_debit:,.2f}") 
        logger.info(f"Total Realized Cash: {total_realized_cash:,.2f}")
        logger.info(f"Total Unrealized P&L: {total_liquidation_value:,.2f}")
        logger.info(f"Final True P&L: {total_realized_cash + total_liquidation_value:,.2f}")
        logger.info(f"--- DEBUG END ---\n")

        return {
            "initial_debit": initial_entry_debit, # # Positive = Net Credit, Negative = Net Debit
            "net_realized": total_realized_cash,  # Current cash state
            "unrealized_pnl": total_liquidation_value,
            "total_comm": total_comm,
            "total_pnl": total_realized_cash + total_liquidation_value
        }

def execute_close_strategy(group_id, exit_details, execution_dt):
    try:
        with SessionLocal() as db:
            for leg_id, details in exit_details.items():
                leg = db.get(Leg, leg_id)
                if leg:
                    leg.exit_price = details['price']
                    leg.exit_commission = details['commission']
                    leg.exit_date = execution_dt  # Using the passed EST datetime
                    leg.status = "Closed"
            
            # Mark the group as closed if your schema supports it
            db.execute(update(TradeGroup).where(TradeGroup.id == group_id).values(status="Closed"))
            
            # 2. Update Group Status and Timestamp
            group = db.get(TradeGroup, group_id)
            if group:
                group.status = "Closed"
                # Explicitly set the timestamp to match the execution date
                group.updated_at = execution_dt 
                
                logger.info(f"✅ TradeGroup {group_id} marked as 'Closed' and updated_at set to {execution_dt}")

            db.commit()

            logger.info(f"💾 Database transaction closed successfully for Group {group_id}.")

            return True
    except Exception as e:
        print(f"Error: {e}")
        return False

def get_active_legs_by_group(group_id):
    """Fetches only active legs for a specific group."""
    with SessionLocal() as db:
        return db.query(Leg).filter(
            Leg.group_id == group_id, 
            Leg.status == "Active"
        ).all()

@st.cache_data(ttl=60)
def fetch_closed_complex_groups():
    with SessionLocal() as db:
        # Fetch groups marked as CLOSED
        groups = (
            db.query(TradeGroup)
            .options(joinedload(TradeGroup.legs))
            .filter(TradeGroup.status == 'Closed')
            .order_by(TradeGroup.id.desc())
            .all()
        )
        return groups