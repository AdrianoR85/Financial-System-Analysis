import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pytz

from utils.data import fetch_intraday, fetch_prices, PERIOD_MAP

ET = pytz.timezone("America/New_York")

COLORS = [
    "#4f8ef7", "#f75f4f", "#4fc98e", "#f7c74f",
    "#c44fff", "#ff914f", "#4ff7f0", "#f74fa0",
]


def _normalize_index(series: pd.Series) -> pd.Series:
    """Convert series index to US/Eastern time."""
    if series.index.tz is None:
        series.index = series.index.tz_localize("UTC")
    series.index = series.index.tz_convert(ET)
    return series


def _ticks_from_data(prices_et: pd.DataFrame, n_days: int) -> tuple[list, list]:
    """
    Derive one tick per trading day from the actual data index.
    Picks the first timestamp of each calendar date present in the data.
    Returns only the last n_days entries.
    """
    if prices_et.empty:
        return [], []

    idx = prices_et.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC").tz_convert(ET)

    # Only consider market hours (9:30–16:00) to avoid pre/post-market dates
    market_idx = idx[(idx.hour > 9) | ((idx.hour == 9) & (idx.minute >= 30))]
    market_idx = market_idx[market_idx.hour < 16]

    if len(market_idx) == 0:
        market_idx = idx  # fallback: use all

    dates_first: dict = {}
    for ts in market_idx:
        d = ts.date()
        if d not in dates_first:
            dates_first[d] = ts

    sorted_dates = sorted(dates_first.keys())[-n_days:]
    tick_vals = [dates_first[d] for d in sorted_dates]
    tick_text = [d.strftime("%a %-m/%-d") for d in sorted_dates]
    return tick_vals, tick_text


def _get_xaxis_config(period: str, now_et: datetime,
                      prices_et: pd.DataFrame) -> dict:
    """
    Returns Plotly xaxis config.

    IMPORTANT:
    - rangebreaks with pattern="hour" only works correctly with intraday (5m) data.
    - For daily data (1M, 3M, 6M, 1Y), only use bounds=["sat","mon"] — no hour breaks.
    - For 5D/10D intraday: use rangebreaks to hide weekends only (no hour bounds,
      because hour bounds can truncate the visible data range unexpectedly).
    """

    if period == "1D":
        return dict(
            tickformat="%-I %p",
            dtick=60 * 60 * 1000,
            tickangle=0,
            range=[
                now_et.replace(hour=9,  minute=30, second=0, microsecond=0),
                now_et.replace(hour=16, minute=0,  second=0, microsecond=0),
            ],
            rangebreaks=[
                dict(bounds=["sat", "mon"]),
                dict(bounds=[16, 9.5], pattern="hour"),
            ],
        )

    elif period in ("5D", "10D"):
        n = 5 if period == "5D" else 10
        tick_vals, tick_text = _ticks_from_data(prices_et, n)

        # For 5D/10D: hide weekends but NOT hour-based breaks.
        # Hour-based breaks on 5m data cause visual truncation when the
        # rangebreak bounds don't align with the tz-aware timestamps.
        # Instead, we set a hard x-range from first to last tick.
        x_range = None
        if tick_vals:
            # Extend range slightly beyond last tick to show full last day
            x_start = tick_vals[0]
            x_end   = prices_et.index[-1] if not prices_et.empty else tick_vals[-1]
            x_range = [x_start, x_end]

        cfg = dict(
            tickvals=tick_vals,
            ticktext=tick_text,
            tickangle=0,
            rangebreaks=[
                dict(bounds=["sat", "mon"]),  # hide weekends only
            ],
        )
        if x_range:
            cfg["range"] = x_range
        return cfg

    elif period == "1M":
        return dict(
            tickformat="%-m/%-d",
            dtick=7 * 24 * 60 * 60 * 1000,   # weekly ticks
            tickangle=0,
            rangebreaks=[dict(bounds=["sat", "mon"])],
        )

    elif period == "3M":
        return dict(
            tickformat="%-m/%-d",
            dtick=14 * 24 * 60 * 60 * 1000,
            tickangle=0,
            rangebreaks=[dict(bounds=["sat", "mon"])],
        )

    elif period == "6M":
        return dict(
            tickformat="%b",
            dtick="M1",
            tickangle=0,
            rangebreaks=[dict(bounds=["sat", "mon"])],
        )

    elif period == "1Y":
        return dict(
            tickformat="%b",
            dtick="M1",
            tickangle=0,
            rangebreaks=[dict(bounds=["sat", "mon"])],
        )

    else:  # 5Y, 10Y — weekly/monthly candles, no rangebreaks needed
        return dict(
            tickformat="%Y",
            dtick="M12",
            tickangle=0,
        )


def _prepend_prev_close(series: pd.Series, now_et: datetime) -> pd.Series:
    """Flat anchor at market open so 1D chart doesn't start mid-air."""
    if series.empty:
        return series
    prev_close = series.iloc[0]
    t_930 = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    if t_930 < series.index[0]:
        pre = pd.Series([prev_close], index=[t_930])
        return pd.concat([pre, series])
    return series


def render_price_chart(tickers: list[str], period: str) -> None:
    # ── CSS ───────────────────────────────────────────────────────────────────
    st.markdown(
        """
        <style>
            span[data-baseweb="tag"] {
                height: 20px !important; padding: 0 6px !important;
                font-size: 11px !important; border-radius: 4px !important;
            }
            span[data-baseweb="tag"] span { font-size:11px !important; line-height:20px !important; }
            span[data-baseweb="tag"] svg  { width:10px !important; height:10px !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── Header ────────────────────────────────────────────────────────────────
    col_title, col_btn = st.columns([6, 1])
    with col_title:
        label = "Today" if period == "1D" else period
        st.markdown(f"### Price — {label}")
    with col_btn:
        manual_refresh = st.button("↻ Refresh", key="manual_refresh")

    # ── Auto-refresh ──────────────────────────────────────────────────────────
    now = datetime.now()
    if "last_refresh" not in st.session_state:
        st.session_state["last_refresh"] = now

    seconds_since = (now - st.session_state["last_refresh"]).total_seconds()
    if manual_refresh or seconds_since >= 300:
        fetch_intraday.clear()
        fetch_prices.clear()
        st.session_state["last_refresh"] = now

    # ── Fetch ─────────────────────────────────────────────────────────────────
    now_et   = datetime.now(ET)
    today_et = now_et.date()

    if period == "1D":
        prices_raw = fetch_intraday(tickers)
    elif period in ("5D", "10D"):
        prices_raw = fetch_prices(tickers, PERIOD_MAP[period], interval="5m")
    else:
        prices_raw = fetch_prices(tickers, PERIOD_MAP[period], interval="1d")

    last_updated = st.session_state["last_refresh"].strftime("%H:%M:%S")
    st.caption(f"Last updated: {last_updated}  ·  Source: yfinance (~15min delay)")

    if prices_raw.empty:
        st.warning("No data available for the selected tickers and period.")
        return

    # Normalize index to ET for tick/range calculation
    prices_et = prices_raw.copy()
    if prices_et.index.tz is None:
        prices_et.index = prices_et.index.tz_localize("UTC")
    prices_et.index = prices_et.index.tz_convert(ET)

    # ── Build figure ──────────────────────────────────────────────────────────
    fig      = go.Figure()
    has_data = False

    for i, ticker in enumerate(tickers):
        if ticker not in prices_raw.columns:
            continue

        color  = COLORS[i % len(COLORS)]
        series = _normalize_index(prices_raw[ticker].dropna().copy())

        if period == "1D":
            series = series[series.index.date == today_et]
            if not series.empty:
                series = _prepend_prev_close(series, now_et)

        if series.empty:
            continue

        has_data = True
        fig.add_trace(go.Scatter(
            x=series.index,
            y=series.values,
            mode="lines",
            name=ticker,
            line=dict(color=color, width=2),
            hovertemplate=f"<b>{ticker}</b><br>%{{x}}<br>$%{{y:.2f}}<extra></extra>",
        ))

    if not has_data:
        st.warning("No data available for the selected tickers and period.")
        return

    # ── Layout ────────────────────────────────────────────────────────────────
    xaxis_cfg = _get_xaxis_config(period, now_et, prices_et)

    fig.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#8a9abf", size=11),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="left", x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=11),
        ),
        xaxis=dict(
            showgrid=False, zeroline=False, title="",
            tickfont=dict(size=10),
            **xaxis_cfg,
        ),
        yaxis=dict(
            showgrid=True, gridcolor="rgba(255,255,255,0.05)",
            zeroline=False, title="",
            tickprefix="$", tickfont=dict(size=10),
        ),
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Countdown ─────────────────────────────────────────────────────────────
    remaining = max(0, 300 - int(seconds_since))
    st.caption(f"Next auto-refresh in {remaining // 60}m {remaining % 60}s")