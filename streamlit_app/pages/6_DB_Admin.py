import streamlit as st
import math
import pandas as pd
from db.models import clear_db_rows, clear_db_schema, Trade
from db.session import Session
from utils.market_clock import show_market_clock
from utils.cleaners import clean_numeric, clean_datetime, clean_bool, clean_str
from utils.trades import calculate_pnl

# Create 2 columns
col1, col2 = st.columns([2,1])  # adjust ratio for spacing
with col1:
    st.title("Database Utilities")
with col2:
    # display the clock banner
    show_market_clock()

# Button to clear all rows (keep schema)
if st.button("Clear all trades (keep schema)"):
    try:
        clear_db_rows()
        st.success("All trades deleted. Schema intact.")
    except Exception as e:
        st.error(f"Error clearing rows: {e}")

# Button to drop & recreate schema
if st.button("Reset database schema (drop + recreate)"):
    try:
        clear_db_schema()
        st.success("Database schema dropped and recreated.")
    except Exception as e:
        st.error(f"Error resetting schema: {e}")

# Upload the  
# Step 1: Upload Excel file
uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])

if uploaded_file:
    # Read Excel into DataFrame
    df = pd.read_excel(uploaded_file)

    # Preview first rows
    st.subheader("Preview of uploaded trades")
    st.dataframe(df.head(10))

    # Step 2: Import into DB
    if st.button("Import to Database"):
        session = Session()
        imported_count = 0

        # Debug the DataFrame before import
        for col in df.columns:
            print(col, df[col].map(type).unique())

        for _, row in df.iterrows():
            trade = Trade(
                symbol=clean_str(row.get("symbol")),
                strategy=clean_str(row.get("strategy")),
                entry_dt=clean_datetime(row.get("entry_date"), row.get("entry_time")),
                exit_dt=clean_datetime(row.get("exit_date"), row.get("exit_time")),
                entry_price=clean_numeric(row.get("entry_price")),
                exit_price=clean_numeric(row.get("exit_price")),
                entry_commissions=clean_numeric(row.get("entry_commissions")),
                exit_commissions=clean_numeric(row.get("exit_commissions")),
                units=clean_numeric(row.get("quantity")),
                expiry_dt=clean_str(row.get("expiry")),
                strikeprice=clean_numeric(row.get("strikeprice"))
            )

            # calculate PnL if exit_price exists
            trade.pnl = calculate_pnl(trade, live_price=None)   # closed trades use exit_price
            if clean_str(row.get("status")) == "CLOSED":
                trade.is_open = False
            else:
                trade.is_open = True

            session.add(trade)
            imported_count += 1
        
        session.commit()
        st.success(f"✅ {imported_count} trades successfully imported into the database!")