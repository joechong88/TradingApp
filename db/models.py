import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
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