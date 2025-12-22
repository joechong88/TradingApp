import streamlit as st
import pandas as pd
import calendar
from datetime import datetime, date
import pytz
from sqlalchemy.orm import Session
from db.models import SessionLocal, Trade
from utils.trades import trades_to_df
import plotly.graph_objects as go
import altair as alt
import pandas_market_calendars as mcal 
from utils.market_clock import show_market_clock

nyse = mcal.get_calendar("NYSE")

@st.cache_data(ttl=60)
def load_closed_trades():
    with SessionLocal() as db:
        trades = (
            db.query(Trade)
            .filter(Trade.is_open == False)
            .order_by(Trade.exit_dt.asc())
            .all()
        )
    return trades_to_df(trades, live=False)

def get_month_schedule(year, month):
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    schedule = nyse.schedule(start_date=start, end_date=end)
    trading_days = set(schedule.index.date)

    return trading_days

def build_daily_stats(df):
    df["exit_date"] = pd.to_datetime(df["exit_dt"]).dt.date

    daily_pnl = df.groupby("exit_date")["pnl"].sum()
    daily_count = df.groupby("exit_date")["pnl"].count()

    return daily_pnl.to_dict(), daily_count.to_dict()

def build_monthly_stats(df):
    # Only closed trades
    closed = df[df["is_open"] == False].copy()

    # Extract year-month
    closed["month"] = closed["exit_dt"].dt.to_period("M")

    # Compute P&L per trade
    closed["pnl"] = (
        (closed["exit_price"] - closed["entry_price"]) * closed["units"]
        - closed["entry_commissions"]
        - closed["exit_commissions"]
    )

    # Win/Loss flags
    closed["is_win"] = closed["pnl"] > 0
    closed["is_loss"] = closed["pnl"] < 0

    # Aggregate
    summary = closed.groupby("month").agg(
        trades_closed=("id", "count"),
        total_pnl=("pnl", "sum"),
        wins=("is_win", "sum"),
        losses=("is_loss", "sum"),
    )

    # Win rate
    summary["win_rate"] = (summary["wins"] / summary["trades_closed"]) * 100
    summary["loss_rate"] = (summary["losses"] / summary["trades_closed"]) * 100

    # Convert PeriodIndex → Timestamp for display
    summary.index = summary.index.to_timestamp()

    return summary

def compute_win_loss(df):
    wins = (df["pnl"] > 0).sum()
    losses = (df["pnl"] < 0).sum()
    breakeven = (df["pnl"] == 0).sum()
    total = len(df)

    return {
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "total": total,
        "win_rate": wins / total if total > 0 else 0
    }

def aggregate_pnl(df):
    df["exit_date"] = pd.to_datetime(df["exit_dt"]).dt.date
    df["exit_week"] = pd.to_datetime(df["exit_dt"]).dt.to_period("W").apply(lambda r: r.start_time.date())
    df["exit_month"] = pd.to_datetime(df["exit_dt"]).dt.to_period("M").apply(lambda r: r.start_time.date())

    daily = df.groupby("exit_date")["pnl"].sum().reset_index()
    weekly = df.groupby("exit_week")["pnl"].sum().reset_index()
    monthly = df.groupby("exit_month")["pnl"].sum().reset_index()

    return daily, weekly, monthly

def get_month_to_date_pnl(df, year, month):
    df["exit_date"] = pd.to_datetime(df["exit_dt"]).dt.date

    month_start = date(year, month, 1)
    today = date.today()

    # Only include trades up to today, and only within the selected month
    mask = (df["exit_date"] >= month_start) & (df["exit_date"] <= today)
    df_mtd = df[mask]

    return df_mtd["pnl"].sum()

def day_color(value, year, month, pnl_map):
    if not value:
        return "background-color: #f0f0f0; color: #999;"

    day = int(value.split("\n")[0])
    date_obj = date(year, month, day)
    pnl = pnl_map.get(date_obj, None)

    if pnl is None:
        return "background-color: #f0f0f0; color: #999;"
    if pnl > 0:
        return "background-color: #c6efce; color: #006100;"
    if pnl < 0:
        return "background-color: #ffc7ce; color: #9c0006;"
    return "background-color: #ffeb9c; color: #7f6000;"

def pnl_to_color(pnl, max_abs_pnl):
    if max_abs_pnl == 0:
        return "#f0f0f0"
    intensity = min(abs(pnl) / max_abs_pnl, 1)

    if pnl > 0:
        return f"rgba(0, 128, 0, {0.15 + 0.65 * intensity})"
    elif pnl < 0:
        return f"rgba(200, 0, 0, {0.15 + 0.65 * intensity})"
    else:
        return "#f0f0f0"

def build_pnl_map(daily_df):
    return {row.exit_date: row.pnl for _, row in daily_df.iterrows()}

def build_calendar_matrix(year, month, pnl_map, count_map, preview_map):
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdatescalendar(year, month)

    trading_days = get_month_schedule(year, month)
    today_et = datetime.now(pytz.timezone("US/Eastern")).date()

    matrix = []
    date_matrix = []    # Parallel matrix of actual dates
    for week in month_days:
        row = []
        date_row = []
        for day in week:
            if day.month != month:
                row.append("")  # blank cell
                date_row.append(None)
                continue

            is_trading_day = day in trading_days
            pnl = pnl_map.get(day, None)
            count = count_map.get(day, 0)
            preview_lines = preview_map.get(day, [])
            
            # Build inner content
            if not is_trading_day:
                extra_html = "<div>Market Closed</div>"
            elif day > today_et and pnl is None:
                #Future trading day with no trades closed yet
                extra_html = "<div style='color:#1e90ff'>FUTURE</div>"
            elif pnl is None:
                extra_html = "<div>No Trades</div>"
            else:
                preview_html = "<br>".join(preview_lines[:3])   # Limit to 3 lines
                extra_html = (
                    f"<div>Trades - {count}</div>"
                    f"<div>${pnl:,.2f}</div>"
                    f"<div style='font-size:11px; color:#333; margin-top:4px;'>{preview_html}</div>"
                )

            bg = get_cell_background(day, pnl, is_trading_day)

            tooltip = " | ".join(preview_lines)
            # Final HTML cell
            label = f"""
             <div class='calendar-cell' title="{tooltip}" style='
                background-color:{bg};
                border: 1px solid #bbb;
                box-shadow: inset 0 0 2px rgba(0,0,0,0.1);
                border-radius:6px;
                padding:4px;
                text-align:center;
                line-height:1.2;
                height:110px;
                color:#000;
            '>
                <div style='font-weight:bold;'>{day.day}</div>
                {extra_html}
            </div>
            """
            row.append(label)
            date_row.append(day)

        matrix.append(row)
        date_matrix.append(date_row)

    df_calendar = pd.DataFrame(
        matrix,
        columns=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    )

    return df_calendar, date_matrix

def render_weekday_labels():
    cols = st.columns(7)
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for col, label in zip(cols, labels):
        col.markdown(
            f"<div style='text-align:center; font-weight:bold; padding-bottom:4px;'>{label}</div>",
            unsafe_allow_html=True
        )

def render_clickable_calendar(df_calendar, date_matrix):
    for row_idx, row in df_calendar.iterrows():
        cols = st.columns(7)
        for col_idx, cell_html in enumerate(row):
            day_date = date_matrix[row_idx][col_idx]

            if not cell_html:
                cols[col_idx].markdown("<div style='height:80px;'></div>", unsafe_allow_html=True)
                continue

            with cols[col_idx]:                
                # 1. Render the calendar cell first
                st.markdown(cell_html, unsafe_allow_html=True)

                # 2. Then render the submit button
                clicked = st.button(label=" ", key=f"daybtn-{row_idx}-{col_idx}", help="Click to view trades")
                st.markdown(f"""
                    <script>
                    var btn = window.parent.document.querySelector('button[kind="secondary"][data-testid="baseButton-root"][aria-label="daybtn-{row_idx}-{col_idx}"]');
                    if (btn) {{
                        btn.classList.add('calendar-click-btn');
                    }}
                    </script>
                """, unsafe_allow_html=True)

                # 3. Handle click
                if clicked and day_date:
                    st.session_state.selected_date = day_date

# --- The styling for the annual calendar with monthly breakdown ---
# 
#
def pnl_to_color(pnl, max_abs_pnl):
    if max_abs_pnl == 0:
        return "#f0f0f0"
    intensity = min(abs(pnl) / max_abs_pnl, 1)

    if pnl > 0:
        return f"rgba(0, 128, 0, {0.15 + 0.65 * intensity})"
    elif pnl < 0:
        return f"rgba(200, 0, 0, {0.15 + 0.65 * intensity})"
    else:
        return "#f0f0f0"

# --- The UI rendering of the annual calendar with monthly breakdown ---
# 
#
def render_monthly_calendar(summary, selected_year):
    start = datetime(selected_year, 1, 1)
    
    all_months = pd.date_range(
        start,
        periods=12,
        freq="MS"
    )
    summary = summary.reindex(all_months, fill_value=0)
    max_abs_pnl = float(summary["total_pnl"].abs().max())

    rows = [st.columns(4), st.columns(4), st.columns(4)]

    for i, month in enumerate(summary.index):
        row = i // 4
        col = i % 4
        m = summary.loc[month].to_dict()
        text_color = "white" if m["trades_closed"] > 0 else "#666"
        text_shadow = "0 1px 2px rgba(0,0,0,0.3)"

        with rows[row][col]:
            if m["trades_closed"] == 0:
                html = f"""
                    <div style="
                        padding: 6px 8px;
                        border-radius: 6px;
                        background-color: #f0f0f0;
                        border: 1px solid #ccc;
                        text-align: center;
                        line-height: 1.2;
                        min-height: 80px;
                        color: #666;
                    ">
                        <div style="font-weight: 600; font-size: 13px; margin-bottom: 2px;">
                            {month.strftime('%b').upper()} {month.year}
                        </div>
                        <div style="font-size: 16px; font-weight: 600; margin-bottom: 2px;">—</div>
                        <div style="font-size: 11px;">No trades</div>
                    </div>
                """
            else:
                bg_color = pnl_to_color(m["total_pnl"], max_abs_pnl)
                html = f"""
                    <div style="
                        padding: 6px 8px;
                        border-radius: 6px;
                        background-color: {bg_color};
                        border: 1px solid #ccc;
                        text-align: center;
                        line-height: 1.2;
                        min-height: 80px;
                    ">
                        <div style="font-weight: 600; font-size: 16px; margin-bottom: 2px;">
                            {month.strftime('%b').upper()} {month.year}
                        </div>
                        <div style="font-size: 18px; font-weight: 700; margin-bottom: 2px; color: {text_color}; text-shadow: {text_shadow};">
                            {m["total_pnl"]:,.0f}
                        </div>
                        <div style="font-size: 13px; color: {text_color}; ; text-shadow: {text_shadow};">
                            {int(m["trades_closed"])} trades • {m["win_rate"]:.0f}% win
                        </div>
                    </div>
                """

            # ✅ This is the critical line
            st.markdown(html, unsafe_allow_html=True)

# --- The 
# 
#
def extract_day(value):
    if not value:
        return None
    try:
        # Extract the first <div> content
        return int(value.split(">")[2].split("<")[0])
    except:
        return None

def get_cell_background(day, pnl, is_trading_day):
    # Market closed (weekend or holiday)
    if not is_trading_day:
        return "#e0e0e0"   # grey

    # Trading day but no trades
    if pnl is None:
        return "#fafafa"   # light grey

    # Profit / Loss / Zero
    if pnl > 0:
        return "#c6efce"   # green
    if pnl < 0:
        return "#ffc7ce"   # red
    return "#ffeb9c"       # yellow

def show_trades_for_date(df, selected_date):
    day_df = df[df["exit_dt"].dt.date == selected_date]

    st.subheader(f"Trades on {selected_date.strftime('%Y-%m-%d')}")

    if day_df.empty:
        st.info("No trades on this day.")
        return

    # You can customize this to your preferred layout
    st.dataframe(day_df)

# Build a function to extract summaries
def build_trade_preview_map(df):
    df["exit_date"] = pd.to_datetime(df["exit_dt"]).dt.date
    preview_map = {}

    for date_val, group in df.groupby("exit_date"):
        lines = []
        for _, row in group.iterrows():
            symbol = row["symbol"]
            pnl = row["pnl"]
            lines.append(f"{symbol}: ${pnl:,.2f}")
        preview_map[date_val] = lines

    return preview_map

# Global CSS
st.markdown("""
    <style>

    .calendar-cell:hover {
        box-shadow: 0 0 4px rgba(0,0,0,0.2);
        transition: box-shadow 0.2s ease-in-out;
    }

    .calendar-click-btn {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        opacity: 0;     /* fully invisible */
        cursor: pointer;
        border: none;
        background: none;
        padding: 0;
        margin: 0;
    }

    .calendar-cell {
        position: relative;     /* required for absolute button overlay */
    }
    </style>
""", unsafe_allow_html=True)

col1, col2 = st.columns([2, 1])
with col1:
    st.title("Dashboard: Closed trades P/L calendar")
with col2:
    show_market_clock(mode="static")

if "selected_date" not in st.session_state:
    st.session_state.selected_date = None

df = load_closed_trades()
pnl_map, count_map = build_daily_stats(df)
preview_map = build_trade_preview_map(df)

if df.empty:
    st.info("No closed trades yet.")
    st.stop()

# Render the annual calendar first
available_years = sorted(set(df["exit_dt"].dt.year))
selected_year = st.selectbox("Select Year", available_years, index=available_years.index(date.today().year))

df_year = df[df["exit_dt"].dt.year == selected_year]
monthly_summary = build_monthly_stats(df_year)
st.markdown(" ", unsafe_allow_html=True)
annual_container = st.container()
with annual_container:
    render_monthly_calendar(monthly_summary, selected_year)

# Create a visual divider
st.markdown("""
    <div style='
        height: 1px;
        background-color: #ddd;
        margin: 35px 0;
    '></div>
""", unsafe_allow_html=True)

# --- 12 months Rolling equity chart for the year ---
# Ensure exit_dt is datetime
df_year["exit_dt"] = pd.to_datetime(df_year["exit_dt"])

# Sort by date
df_year = df_year.sort_values("exit_dt")

# Compute daily P&L
daily = df_year.groupby(df_year["exit_dt"].dt.date)["pnl"].sum().reset_index()
daily["exit_date"] = pd.to_datetime(daily["exit_dt"])

# Compute rolling equity
daily["equity"] = daily["pnl"].cumsum()

# Safety check
if daily.empty:
    st.info("No trades for this year - equity curve unavailable.")
else:
    st.subheader(f"Rolling 12 months Equity Curve for - {selected_year}")

    annual_rolling_chart = (
        alt.Chart(daily)
        .mark_line(color="#2ecc71", strokeWidth=2)
        .encode(
            x=alt.X("exit_date:T", title="Date"),
            y=alt.Y("equity:Q", title="Equity (Cumulative P&L)"),
            tooltip=["exit_date:T", "pnl:Q", "equity:Q"]
        )
        .properties(height=300)
    )

    st.altair_chart(annual_rolling_chart, use_container_width=True)

# Create a visual divider
st.markdown("""
    <div style='
        height: 1px;
        background-color: #ddd;
        margin: 35px 0;
    '></div>
""", unsafe_allow_html=True)

# User selects month + year
col1, col2 = st.columns(2)
year = col1.selectbox("Year", list(range(2020, 2031)), index=list(range(2020,2031)).index(date.today().year))
month = col2.selectbox("Month", list(range(1, 13)), index=date.today().month - 1)

calendar_df, date_matrix = build_calendar_matrix(year, month, pnl_map, count_map, preview_map)
mtd_pnl = get_month_to_date_pnl(df, year, month)

# Color logic
color = "#2ecc71" if mtd_pnl > 0 else "#e74c3c" if mtd_pnl < 0 else "#f1c40f"

# --- Summary Metrics ---
stats = compute_win_loss(df)
col1, col2, col3, col4 = st.columns(4)
col1.metric("Winning Trades", stats["wins"])
col2.metric("Losing Trades", stats["losses"])
col3.metric("Breakeven", stats["breakeven"])
col4.metric("Win Rate", f"{stats['win_rate']*100:.1f}%")

# --- P&L Aggregations ---
daily, weekly, monthly = aggregate_pnl(df)

# Render the calendar
st.subheader(f"P&L Calendar — {calendar.month_name[month]} {year}")

# Show the selected month's up-to-date PnL
st.markdown(
    f"""
    <div style="
        background-color:{color};
        padding:14px;
        border-radius:8px;
        color:white;
        font-size:22px;
        font-weight:600;
        text-align:center;
        margin-top:10px;
        margin-bottom:20px;
    ">
        Month‑to‑Date P&L: ${mtd_pnl:,.2f}
    </div>
    """,
    unsafe_allow_html=True
)
render_weekday_labels()
render_clickable_calendar(calendar_df, date_matrix)

# Drill-down section
if st.session_state.selected_date:
    show_trades_for_date(df, st.session_state.selected_date)

st.subheader(f"Rolling Equity Curve for - {calendar.month_name[month]} {year}")

# Build rolling equity curve
equity_curve = daily.copy()
equity_curve["equity"] = equity_curve["pnl"].cumsum()

# Rolling equity chart for the month
equity_chart = (
    alt.Chart(equity_curve)
    .mark_line(color="#2ecc71", strokeWidth=2)
    .encode(
        x=alt.X("exit_date:T", title="Date"),
        y=alt.Y("equity:Q", title="Equity (Cumulative P&L)"),
        tooltip=["exit_date:T", "pnl:Q", "equity:Q"]
    )
    .properties(height=300)
)

st.altair_chart(equity_chart, use_container_width=True)

# Weekly P&L
st.subheader("Weekly P&L")
st.bar_chart(weekly.set_index("exit_week"))