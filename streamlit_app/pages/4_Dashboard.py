import streamlit as st
import pandas as pd
import calendar
from datetime import datetime
from sqlalchemy.orm import Session
from db.models import SessionLocal, Trade
import plotly.graph_objects as go

st.title("Dashboard: Closed trades P/L calendar")

def fetch_closed():
    with SessionLocal() as db:  # type: Session
        trades = db.query(Trade).filter(Trade.is_open == False).all()
        return trades

def calc_closed_pl(trade):
    if trade.exit_price is None or trade.entry_price is None:
        return 0.0
    # Long/Short handling; options would be refined per contract multiplier
    multiplier = 1.0
    if trade.strategy.lower() in ["call", "put"]:
        multiplier = 100.0  # standard options multiplier
    direction = 1.0 if trade.strategy.lower() == "long" or trade.strategy.lower() == "call" else -1.0
    gross = (trade.exit_price - trade.entry_price) * trade.units * direction * multiplier
    fees = trade.commissions or 0.0
    return gross - fees

def aggregate_daily_pl(closed_trades):
    rows = []
    for t in closed_trades:
        if not t.exit_dt:
            continue
        day = pd.Timestamp(t.exit_dt).date()
        rows.append({"date": day, "pl": calc_closed_pl(t)})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["date", "pl"])
    return df.groupby("date", as_index=False)["pl"].sum()

def build_calendar_heatmap(month: int, year: int, daily_df: pd.DataFrame):
    cal = calendar.Calendar()
    days = [d for d in cal.itermonthdates(year, month)]
    values = []
    text = []
    for d in days:
        pl = float(daily_df[daily_df["date"] == d]["pl"].sum()) if not daily_df.empty else 0.0
        values.append(pl)
        text.append(f"{d.isoformat()}<br>P/L: {pl:.2f}")
    # 7 columns x n weeks
    weeks = []
    week_vals = []
    week_text = []
    for i, d in enumerate(days):
        if i % 7 == 0 and i != 0:
            weeks.append(week_vals)
            week_vals = []
            week_text.append(text[i-7:i])
        week_vals.append(values[i])
    weeks.append(week_vals)
    # Build z matrix
    z = weeks
    fig = go.Figure(data=go.Heatmap(
        z=z,
        colorscale="RdYlGn",
        showscale=True,
        hoverinfo="text",
        text=sum(week_text, []) if week_text else text
    ))
    fig.update_layout(
        title=f"Daily P/L Heatmap for {calendar.month_name[month]} {year}",
        xaxis=dict(showgrid=False, showticklabels=False),
        yaxis=dict(showgrid=False, showticklabels=False),
        height=500
    )
    return fig

closed = fetch_closed()
daily = aggregate_daily_pl(closed)

# Month/year filter
today = datetime.today()
col1, col2 = st.columns(2)
with col1:
    month = st.selectbox("Month", list(range(1, 13)), index=today.month-1)
with col2:
    year = st.number_input("Year", value=today.year, step=1)

# Filter daily df to selected month/year
if not daily.empty:
    daily_filtered = daily[(pd.to_datetime(daily["date"]).dt.month == month) &
                           (pd.to_datetime(daily["date"]).dt.year == year)]
else:
    daily_filtered = daily

fig = build_calendar_heatmap(month, year, daily_filtered)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Closed trades summary")
summary = daily_filtered["pl"].sum() if not daily_filtered.empty else 0.0
st.metric("Total P/L (selected month)", f"{summary:.2f}")