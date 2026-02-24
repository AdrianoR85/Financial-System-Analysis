import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pytz

from utils.data import fetch_intraday, fetch_prices, PERIOD_MAP

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
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


def _get_xaxis_config(period: str, now_et: datetime) -> dict:
    """
    Returns Plotly xaxis config matching Yahoo Finance style per period.
    
    For 5D/10D: uses two separate traces approach — tickvals for the hour
    labels and date labels are placed separately to avoid overlap.
    """

    if period == "1D":
        return dict(
            tickformat="%-I:%M %p",
            dtick=60 * 60 * 1000,       # every 1 hour in ms
            tickangle=0,
            range=[
                now_et.replace(hour=6,  minute=0, second=0, microsecond=0),
                now_et.replace(hour=18, minute=0, second=0, microsecond=0),
            ],
        )

    elif period in ("5D", "10D"):
        # Build hour ticks (10:00 AM) and date ticks (2/18) separately
        # Hour ticks: placed AT 10:00 AM of each trading day
        # Date ticks: placed AT 12:00 PM (midday) so they appear centered

        days    = 5 if period == "5D" else 10
        start   = (now_et - timedelta(days=days + 3)).replace(
                    hour=0, minute=0, second=0, microsecond=0)

        hour_vals, hour_text = [], []
        date_vals, date_text = [], []

        current = start
        while current.date() <= now_et.date():
            if current.weekday() < 5:  # skip weekends
                # 10:00 AM tick
                t_10am = current.replace(hour=10, minute=0, second=0, microsecond=0)
                hour_vals.append(t_10am)
                hour_text.append("10:00 AM")

                # Date label at noon, format M/D
                t_noon = current.replace(hour=12, minute=0, second=0, microsecond=0)
                date_vals.append(t_noon)
                date_text.append(current.strftime("%-m/%-d"))

            current += timedelta(days=1)

        # Interleave: hour ticks show "10:00 AM", date ticks show "M/D"
        # We place them all in tickvals+ticktext; Plotly renders in order
        all_vals = hour_vals + date_vals
        all_text = hour_text + date_text

        # Sort by time so they render in order
        combined = sorted(zip(all_vals, all_text), key=lambda x: x[0])
        sorted_vals, sorted_text = zip(*combined) if combined else ([], [])

        return dict(
            tickvals=list(sorted_vals),
            ticktext=list(sorted_text),
            tickangle=0,
        )

    elif period in ("1M", "3M", "6M"):
        dtick_days = 5 if period == "1M" else 14
        return dict(
            tickformat="%-m/%-d",
            dtick=dtick_days * 24 * 60 * 60 * 1000,
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
    """
    Fills the pre-market gap (6:00 AM – 9:30 AM) with the previous day's
    closing price. This avoids an empty left side on the 1D chart.

    Strategy: fetch the last known close from the series itself (last point
    before today) or use the first available intraday point as fallback,
    then prepend two anchor points at 6:00 AM and 9:29 AM.
    """
    today = now_et.date()

    # Get yesterday's close — use the first intraday point as proxy
    # (it's the closest we have without an extra API call)
    prev_close = series.iloc[0] if not series.empty else None

    if prev_close is None:
        return series

    # Two anchor points: open of pre-market (6:00 AM) and just before open (9:29 AM)
    t_600  = now_et.replace(hour=6,  minute=0,  second=0, microsecond=0)
    t_929  = now_et.replace(hour=9,  minute=29, second=0, microsecond=0)

    pre_market = pd.Series(
        [prev_close, prev_close],
        index=[t_600, t_929],
    )

    return pd.concat([pre_market, series])


def render_price_chart(tickers: list[str], period: str) -> None:
    """
    Renders the price chart for the selected period.

      1D        → 5min candles, today, 6AM–6PM ET, pre-market filled with prev close
      5D/10D    → 5min candles, two-level X axis (10:00 AM + M/D date)
      1M–6M     → daily candles, date ticks every 5 or 14 days
      1Y        → daily candles, monthly ticks
      5Y/10Y    → weekly/monthly candles, yearly ticks
    """

    # ── CSS: smaller multiselect chips ───────────────────────────────────────
    st.markdown(
        """
        <style>
            span[data-baseweb="tag"] {
                height: 20px !important;
                padding: 0 6px !important;
                font-size: 11px !important;
                border-radius: 4px !important;
            }
            span[data-baseweb="tag"] span {
                font-size: 11px !important;
                line-height: 20px !important;
            }
            span[data-baseweb="tag"] svg {
                width: 10px !important;
                height: 10px !important;
            }
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

    # ── Build figure ──────────────────────────────────────────────────────────
    fig      = go.Figure()
    has_data = False

    for i, ticker in enumerate(tickers):
        if ticker not in prices_raw.columns:
            continue

        color  = COLORS[i % len(COLORS)]
        series = _normalize_index(prices_raw[ticker].dropna().copy())

        if period == "1D":
            # Keep only today's candles then prepend prev close for pre-market
            series = series[series.index.date == today_et]
            if not series.empty:
                series = _prepend_prev_close(series, now_et)

        if series.empty:
            continue

        has_data = True

        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                mode="lines",
                name=ticker,
                line=dict(color=color, width=2),
                hovertemplate=(
                    f"<b>{ticker}</b><br>"
                    "%{x}<br>"
                    "Price: $%{y:.2f}<extra></extra>"
                ),
            )
        )

    if not has_data:
        st.warning("No data available for the selected tickers and period.")
        return

    # ── X axis ────────────────────────────────────────────────────────────────
    xaxis_cfg = _get_xaxis_config(period, now_et)

    fig.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#8a9abf", size=11),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
        ),
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            title="",
            tickfont=dict(size=10),
            **xaxis_cfg,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.05)",
            zeroline=False,
            title="",
            tickprefix="$",
            tickfont=dict(size=10),
        ),
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Countdown ─────────────────────────────────────────────────────────────
    remaining = max(0, 300 - int(seconds_since))
    st.caption(f"Next auto-refresh in {remaining // 60}m {remaining % 60}s")