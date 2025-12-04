import asyncio

# Ensure an event loop exists before anything else
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import os, yaml, json
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from ibkr.data import get_live_quote, get_historical_ohlc, calc_pdh_pdl
from charts.plotly_charts import candle_chart, add_ema
from charts.overlays import add_risk_reward_shapes, add_levels

load_dotenv()

@st.cache_data(ttl=3)
def load_config():
    with open(os.path.join("config", "preferences.yaml"), "r") as f:
        return yaml.safe_load(f)

@st.cache_data(ttl=5)
def cached_quote(symbol: str):
    return get_live_quote(symbol)

@st.cache_data(ttl=60)
def cached_ohlc(symbol: str, duration="2 D", bar_size="5 mins"):
    df = get_historical_ohlc(symbol, duration, bar_size)
    return json.loads(df.to_json(date_format="iso"))

st.title("Home")

cfg = load_config()
symbol = os.getenv("DEFAULT_SYMBOL", "SPY")

quote = cached_quote(symbol)
ohlc_json = cached_ohlc(symbol)
df = pd.read_json(json.dumps(ohlc_json))
df.index = pd.to_datetime(df["Date"] if "Date" in df.columns else df.index)

layout_cfg = {
    "theme": cfg.get("chart", {}).get("theme", "light"),
    "height": cfg.get("chart", {}).get("layout", {}).get("height", 700),
    "width": cfg.get("chart", {}).get("layout", {}).get("width", 1200),
}
fig = candle_chart(df, layout_cfg)

if "EMA20" in cfg.get("preferences", {}).get("indicators", []):
    add_ema(fig, df, 20, "#1f77b4")
if "EMA50" in cfg.get("preferences", {}).get("indicators", []):
    add_ema(fig, df, 50, "#ff7f0e")
add_levels(fig, calc_pdh_pdl(df))

rr = cfg.get("preferences", {}).get("risk_reward", {})
add_risk_reward_shapes(fig, rr.get("entry"), rr.get("stop"), rr.get("target"))

left, right = st.columns(2)
with left:
    st.subheader("IBKR custom chart")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Symbol: {symbol} | Last: {quote.get('last')} | Bid: {quote.get('bid')} | Ask: {quote.get('ask')}")

with right:
    st.subheader("TradingView chart")
    tv_cfg = cfg.get("tradingview", {})
    if tv_cfg.get("enabled", True):
        tv_symbol = tv_cfg.get("symbol", "NASDAQ:MSFT")
        tv_interval = tv_cfg.get("interval", "D")
        tv_theme = tv_cfg.get("theme", "light")
        html = f"""
        <div class="tradingview-widget-container">
          <div id="tradingview_chart"></div>
          <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
          <script type="text/javascript">
            new TradingView.widget({{
              "width": "100%",
              "height": 700,
              "symbol": "{tv_symbol}",
              "interval": "{tv_interval}",
              "timezone": "Etc/UTC",
              "theme": "{tv_theme}",
              "style": "1",
              "locale": "en",
              "toolbar_bg": "#f1f3f6",
              "enable_publishing": false,
              "allow_symbol_change": true,
              "container_id": "tradingview_chart"
            }});
          </script>
        </div>
        """
        st.components.v1.html(html, height=720)
    else:
        st.info("TradingView embedding disabled by config.")