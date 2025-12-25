import streamlit as st
import pandas as pd
import calendar
from datetime import datetime, date
import pytz
from sqlalchemy.orm import Session
from db.models import SessionLocal, Trade
from utils.trades import trades_to_df, calculate_pnl
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

    # Win/Loss flags
    closed["is_win"] = closed["pnl"] > 0
    closed["is_loss"] = closed["pnl"] < 0

    # Aggregate
    summary = closed.groupby("month").agg(
        trades_closed=("id", "count"),
        total_pnl=("pnl", "sum"),
        wins=("is_win", "sum") if "is_win" in closed else ("pnl", lambda x: (x>0).sum()),
        losses=("is_loss", "sum") if "is_loss" in closed else ("pnl", lambda x: (x<0).sum()),
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

def build_rolling_12m_equity_chart(df_year):
    """
    Build a 12‑month rolling cumulative equity chart with:
    - daily P&L aggregation
    - cumulative equity
    - drawdown shading
    - hover marker + tooltip
    """

    import altair as alt
    import pandas as pd

    # Ensure datetime
    df_year = df_year.copy()
    df_year["exit_dt"] = pd.to_datetime(df_year["exit_dt"])

    # Daily P&L
    daily = (
        df_year
        .groupby(df_year["exit_dt"].dt.date)["pnl"]
        .sum()
        .reset_index()
        .rename(columns={"exit_dt": "exit_date"})
    )

    # Convert to datetime
    daily["exit_date"] = pd.to_datetime(daily["exit_date"])

    # Cumulative equity
    daily["equity"] = daily["pnl"].cumsum()

    # Running max for drawdown shading
    daily["running_max"] = daily["equity"].cummax()

    # Base chart
    base = alt.Chart(daily).encode(
        x=alt.X("exit_date:T", title="Date")
    )

    # Drawdown shading
    drawdown_area = base.mark_area(
        opacity=0.25,
        color="#e74c3c"
    ).encode(
        y="equity:Q",
        y2="running_max:Q"
    )

    # Equity line
    equity_line = base.mark_line(
        color="#2ecc71",
        strokeWidth=2
    ).encode(
        y=alt.Y("equity:Q", title="Equity (Cumulative P&L)")
    )

    # Hover selector
    hover = alt.selection_point(
        fields=["exit_date"],
        nearest=True,
        on="mouseover",
        empty="none",
        clear="mouseout"
    )

    # Hover point marker
    points = base.mark_circle(size=65, color="#2ecc71").encode(
        y="equity:Q",
        opacity=alt.condition(hover, alt.value(1), alt.value(0))
    ).add_params(hover)

    # Tooltip
    tooltips = base.mark_rule(color="#aaa").encode(
        y="equity:Q",
        tooltip=[
            alt.Tooltip("exit_date:T", title="Date"),
            alt.Tooltip("pnl:Q", title="Daily P&L", format=",.0f"),
            alt.Tooltip("equity:Q", title="Equity", format=",.0f"),
        ]
    ).transform_filter(hover)

    # Final chart
    chart = (drawdown_area + equity_line + points + tooltips).properties(
        height=300
    )

    return chart

def build_monthly_equity_curve_chart(daily_month):
    """
    Build a monthly rolling cumulative equity curve with:
    - daily P&L aggregation
    - cumulative equity
    - drawdown shading
    - hover marker + tooltip
    """

    import altair as alt
    import pandas as pd

    daily = daily_month.copy()
    daily["exit_date"] = pd.to_datetime(daily["exit_date"])

    # Cumulative equity
    daily["equity"] = daily["pnl"].cumsum()

    # Running max for drawdown shading
    daily["running_max"] = daily["equity"].cummax()

    # Base chart
    base = alt.Chart(daily).encode(
        x=alt.X("exit_date:T", title="Date")
    )

    # Drawdown shading
    drawdown_area = base.mark_area(
        opacity=0.25,
        color="#e74c3c"
    ).encode(
        y="equity:Q",
        y2="running_max:Q"
    )

    # Equity line
    equity_line = base.mark_line(
        color="#2ecc71",
        strokeWidth=2
    ).encode(
        y=alt.Y("equity:Q", title="Equity (Cumulative P&L)")
    )

    # Hover selector
    hover = alt.selection_point(
        fields=["exit_date"],
        nearest=True,
        on="mouseover",
        empty="none",
        clear="mouseout"
    )

    # Hover point marker
    points = base.mark_circle(size=65, color="#2ecc71").encode(
        y="equity:Q",
        opacity=alt.condition(hover, alt.value(1), alt.value(0))
    ).add_params(hover)

    # Tooltip
    tooltips = base.mark_rule(color="#aaa").encode(
        y="equity:Q",
        tooltip=[
            alt.Tooltip("exit_date:T", title="Date"),
            alt.Tooltip("pnl:Q", title="Daily P&L", format=",.0f"),
            alt.Tooltip("equity:Q", title="Equity", format=",.0f"),
        ]
    ).transform_filter(hover)

    return (drawdown_area + equity_line + points + tooltips).properties(height=300)

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
    st.title("Dashboard P&L calendar")
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

# --- TABS SETUP ---
tab_annual, tab_monthly = st.tabs(["📊 Annual Performance", "📅 Monthly Calendar View"])

# ---------------------------------------------------------
# TAB 1: ANNUAL VIEW
# ---------------------------------------------------------
with tab_annual:
    available_years = sorted(set(df["exit_dt"].dt.year), reverse=True)
    selected_year = st.selectbox("Select Year to Analyze", available_years, key="year_selector_annual")

    df_year = df[df["exit_dt"].dt.year == selected_year].copy()
    monthly_summary = build_monthly_stats(df_year)

    # Annual Heatmap Blocks
    st.markdown("### Monthly Performance Summary")
    render_monthly_calendar(monthly_summary, selected_year)

    st.markdown("---")

    # Annual Rolling Equity
    st.subheader(f"Equity Curve - {selected_year}")
    
    # Filter for NYSE trading days to ensure clean chart
    schedule = nyse.schedule(start_date=f"{selected_year}-01-01", end_date=f"{selected_year}-12-31")
    trading_days_year = pd.to_datetime(schedule.index.date)
    
    df_year_chart = df_year.copy()
    df_year_chart["exit_date"] = pd.to_datetime(df_year_chart["exit_dt"]).dt.date
    df_year_chart = df_year_chart[pd.to_datetime(df_year_chart["exit_date"]).isin(trading_days_year)]

    if not df_year_chart.empty:
        annual_rolling_chart = build_rolling_12m_equity_chart(df_year_chart)
        st.altair_chart(annual_rolling_chart, width='stretch')
    else:
        st.warning("No trading day data available for this year.")

# ---------------------------------------------------------
# TAB 2: MONTHLY VIEW
# ---------------------------------------------------------
with tab_monthly:
    # Controls for Month/Year
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        m_year = st.selectbox("Year", list(range(2020, 2031)), index=list(range(2020, 2031)).index(date.today().year))
    with c2:
        m_month = st.selectbox("Month", list(range(1, 13)), index=date.today().month - 1)
    
    # Metrics Bar
    stats = compute_win_loss(df[(df["exit_dt"].dt.year == m_year) & (df["exit_dt"].dt.month == m_month)])
    current_month_dates = [d for d in pnl_map.keys() if d.year == m_year and d.month == m_month]    
    mtd_pnl = sum(pnl_map[d] for d in current_month_dates)

    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    m_col1.metric("MTD P&L", f"${mtd_pnl:,.2f}")
    m_col2.metric("Wins", stats["wins"])
    m_col3.metric("Losses", stats["losses"])
    m_col4.metric("Win Rate", f"{stats['win_rate']*100:.1f}%")

    st.markdown("---")

    # Calendar Rendering
    st.subheader(f"{calendar.month_name[m_month]} {m_year} Calendar")
    calendar_df, date_matrix = build_calendar_matrix(m_year, m_month, pnl_map, count_map, preview_map)
    
    render_weekday_labels()
    render_clickable_calendar(calendar_df, date_matrix)

    # Drill-down (Shown only if a day is clicked)
    if st.session_state.get("selected_date"):
        st.markdown("---")
        show_trades_for_date(df, st.session_state.selected_date)
        if st.button("Clear Selection"):
            st.session_state.selected_date = None
            st.rerun()

    st.markdown("---")

    # Monthly Equity Curve
    st.subheader("Monthly Equity Growth")
    daily_all, _, _ = aggregate_pnl(df)
    daily_all["exit_date"] = pd.to_datetime(daily_all["exit_date"])
    
    daily_month = daily_all[
        (daily_all["exit_date"].dt.year == m_year) & 
        (daily_all["exit_date"].dt.month == m_month)
    ].copy()

    if not daily_month.empty:
        # Filter for trading days
        month_start = date(m_year, m_month, 1)
        month_end = date(m_year, m_month, calendar.monthrange(m_year, m_month)[1])
        m_schedule = nyse.schedule(start_date=month_start, end_date=month_end)
        m_trading_days = pd.to_datetime(m_schedule.index.date)
        
        daily_month = daily_month[daily_month["exit_date"].isin(m_trading_days)]
        chart_month = build_monthly_equity_curve_chart(daily_month)
        st.altair_chart(chart_month, width='stretch')
    else:
        st.info("No trades closed in this month to display equity curve.")