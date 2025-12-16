# db/session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Create engine (replace with your DB URL)
engine = create_engine("sqlite:///trading_app.db", echo=True)

# Create session factory
Session = sessionmaker(bind=engine)