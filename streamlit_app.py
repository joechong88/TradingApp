import streamlit as st
import pandas as pd
from src.trading_app.data.provider import fake_price_series
from src.trading_app.strategies.example_strategy import SMACrossover

st.title("TradingApp — Example SMA Crossover")

symbol = st.text_input("Symbol", "FAKE")
short = st.number_input("Short window", min_value=2, value=10)
long = st.number_input("Long window", min_value=3, value=30)

prices = fake_price_series(symbol, n=200, seed=42)
st.line_chart(prices)

strat = SMACrossover(short_window=short, long_window=long)
sig = strat.signals(prices)
st.write("Latest signal:", int(sig.iloc[-1]))

if st.button("Print signal series"):
    st.write(sig.tail(20))
