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


def _ticks_from_data(df: pd.DataFrame, n_days: int) -> tuple[list, list]:
    """
    Derives X-axis tick positions directly from the data index.
    For each unique trading date in the data, places a tick at the first
    available timestamp of that day.  This guarantees ticks match the data
    and never skips or duplicates days.

    Returns (tick_vals, tick_text) lists ready for Plotly tickvals/ticktext.
    """
    if df.empty:
        return [], []

    # Collect all timestamps across all tickers, normalize to ET
    all_idx: pd.DatetimeIndex = df.index
    if all_idx.tz is None:
        all_idx = all_idx.tz_localize("UTC")
    all_idx = all_idx.tz_convert(ET)

    # Group by calendar date, pick the first timestamp of each day
    dates_seen: dict = {}
    for ts in sorted(all_idx):
        d = ts.date()
        if d not in dates_seen:
            dates_seen[d] = ts

    # Keep only the last n_days trading days
    sorted_dates = sorted(dates_seen.keys())[-n_days:]

    tick_vals = [dates_seen[d] for d in sorted_dates]
    tick_text = [d.strftime("%a %-m/%-d") for d in sorted_dates]  # e.g. "Thu 2/20"

    return tick_vals, tick_text


def _get_xaxis_config(period: str, now_et: datetime,
                      prices_raw: pd.DataFrame) -> dict:
    """Returns Plotly xaxis config for the given period."""

    if period == "1D":
        return dict(
            tickformat="%-I %p",
            dtick=60 * 60 * 1000,
            tickangle=0,
            range=[
                now_et.replace(hour=9,  minute=30, second=0, microsecond=0),
                now_et.replace(hour=16, minute=0,  second=0, microsecond=0),
            ],
        )

    elif period in ("5D", "10D"):
        n = 5 if period == "5D" else 10
        tick_vals, tick_text = _ticks_from_data(prices_raw, n)
        return dict(
            tickvals=tick_vals,
            ticktext=tick_text,
            tickangle=0,
        )

    elif period == "1M":
        return dict(
            tickformat="%-m/%-d",
            dtick=5 * 24 * 60 * 60 * 1000,
            tickangle=0,
        )

    elif period == "3M":
        return dict(
            tickformat="%-m/%-d",
            dtick=14 * 24 * 60 * 60 * 1000,
            tickangle=0,
        )

    elif period == "6M":
        return dict(
            tickformat="%b %-d",
            dtick="M1",
            tickangle=0,
        )

    elif period == "1Y":
        return dict(
            tickformat="%b",
            dtick="M1",
            tickangle=0,
        )

    else:  # 5Y, 10Y
        return dict(
            tickformat="%Y",
            dtick="M12",
            tickangle=0,
        )


def _prepend_prev_close(series: pd.Series, now_et: datetime) -> pd.Series:
    """Fill pre-market gap with a flat anchor at the first available price."""
    if series.empty:
        return series
    prev_close = series.iloc[0]
    t_900 = now_et.replace(hour=9,  minute=0,  second=0, microsecond=0)
    t_929 = now_et.replace(hour=9,  minute=29, second=0, microsecond=0)
    pre   = pd.Series([prev_close, prev_close], index=[t_900, t_929])
    return pd.concat([pre, series])


def render_price_chart(tickers: list[str], period: str) -> None:
    # ── CSS ───────────────────────────────────────────────────────────────────
    st.markdown(
        """
        <style>
            span[data-baseweb="tag"] {
                height: 20px !important; padding: 0 6px !important;
                font-size: 11px !important; border-radius: 4px !important;
            }
            span[data-baseweb="tag"] span { font-size: 11px !important; line-height: 20px !important; }
            span[data-baseweb="tag"] svg  { width: 10px !important; height: 10px !important; }
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

    # Normalize the raw DataFrame index to ET for tick calculation
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

    # ── X axis (pass normalized df for tick derivation) ───────────────────────
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