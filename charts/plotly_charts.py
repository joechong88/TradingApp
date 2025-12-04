import pandas as pd
import plotly.graph_objects as go

def candle_chart(df: pd.DataFrame, layout_cfg: dict):
    fig = go.Figure(data=[
        go.Candlestick(
            x=df.index,
            open=df["Open"], high=df["High"],
            low=df["Low"], close=df["Close"],
            name="Price"
        )
    ])
    fig.update_layout(
        title="IBKR Custom Chart",
        xaxis_title="Time",
        yaxis_title="Price",
        template="plotly_white" if layout_cfg.get("theme", "light") == "light" else "plotly_dark",
        height=layout_cfg.get("height", 700),
        width=layout_cfg.get("width", 1200),
        margin=dict(l=40, r=40, t=60, b=40),
        xaxis_rangeslider_visible=False
    )
    return fig

def add_ema(fig, df: pd.DataFrame, period: int, color: str):
    ema = df["Close"].ewm(span=period, adjust=False).mean()
    fig.add_trace(go.Scatter(x=df.index, y=ema, name=f"EMA {period}", line=dict(color=color, width=1.5)))