import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from dotenv import load_dotenv
from typing import List, Optional, Dict, Any
import pandas as pd

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///trading_app.db")

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    strategy = Column(String)  # Long, Short, Call, Put
    units = Column(Float)
    strikeprice = Column(Float, nullable=True)  # for options
    expiry_dt = Column(String, nullable=True)  # for options, store as string YYYYMMDD
    entry_price = Column(Float)
    expected_rr = Column(Float)
    entry_dt = Column(DateTime)   # store in UTC; convert to ET on display
    entry_commissions = Column(Float, default=0.0)
    is_open = Column(Boolean, default=True)

    # Exit details
    exit_price = Column(Float, nullable=True)
    exit_dt = Column(DateTime, nullable=True)
    exit_commissions = Column(Float, nullable=True)

    # Derived snapshots (optional)
    notes = Column(String, nullable=True)

class TradeGroup(Base):
    __tablename__ = "trade_groups"
    id = Column(Integer, primary_key=True)
    strategy_name = Column(String)
    status = Column(String, default="Open")
    notes = Column(String) # Overall strategy thesis (e.g., "Earnings play")
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    legs = relationship("Leg", back_populates="group")

class Leg(Base):
    __tablename__ = "legs"
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("trade_groups.id"))
    symbol = Column(String)
    side = Column(String)
    quantity = Column(Integer)
    status = Column(String) # Active/Closed/Rolled
    strikeprice = Column(Float)
    expiry_dt = Column(String) # YYYYMMDD format
    option_type = Column(String) # C for Call or P for Put
    
    # Permanent Entry Columns
    entry_date = Column(DateTime)
    entry_price = Column(Float)
    entry_commission = Column(Float, default=0.0)
    
    # Permanent Exit Columns
    exit_date = Column(DateTime)
    exit_price = Column(Float)
    exit_commission = Column(Float, default=0.0)
    
    group = relationship("TradeGroup", back_populates="legs")
    transactions = relationship("Transaction", back_populates="leg")

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    leg_id = Column(Integer, ForeignKey("legs.id"))
    
    # Execution Details
    action = Column(String)  # BTO, STO, BTC, STC
    quantity = Column(Integer)
    price = Column(Float)    # The execution price per unit
    commission = Column(Float, default=0.0) # The total commission for this fill
    
    timestamp = Column(DateTime, default=func.now())
    notes = Column(String)   # Optional: e.g., "Part of a roll"
    
    leg = relationship("Leg", back_populates="transactions")

def init_db():
    Base.metadata.create_all(bind=engine)

def clear_db_schema():
    """ Drop all tables and re-create them """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

def clear_db_rows():
    """Delete all rows from the trades table (keep schema)."""
    with SessionLocal() as db:
        db.query(Trade).delete()
        db.commit()