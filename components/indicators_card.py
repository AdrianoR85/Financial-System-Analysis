import math
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from utils.indicators import (
    fetch_financials,
    get_current_price_data,
    get_pe_pb,
    slice_sparkline,
)

# ─── COLORS ───────────────────────────────────────────────────────────────────
TICKER_COLORS = [
    "#4f8ef7", "#f75f4f", "#4fc98e", "#f7c74f",
    "#c44fff", "#ff914f", "#4ff7f0", "#f74fa0",
]

# ─── CSS injected once ────────────────────────────────────────────────────────
_CSS_INJECTED = False

def _inject_css():
    global _CSS_INJECTED
    if _CSS_INJECTED:
        return
    st.markdown(
        """
        <style>
        /* Clip sparkline charts so they don't overflow indicator cards */
        .spark-wrap {
            overflow: hidden;
            height: 44px;
            margin: 0;
            padding: 0;
        }
        .spark-wrap iframe,
        .spark-wrap > div {
            height: 44px !important;
            overflow: hidden !important;
        }
        /* Reduce gap between indicator mini-cards */
        [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlock"] {
            gap: 2px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _CSS_INJECTED = True


# ─── FORMATTERS ───────────────────────────────────────────────────────────────
def _fmt_currency(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "--"
    val = float(val)
    if abs(val) >= 1e9:
        return f"${val/1e9:.1f}B"
    if abs(val) >= 1e6:
        return f"${val/1e6:.1f}M"
    if abs(val) >= 1e3:
        return f"${val/1e3:.1f}K"
    return f"${val:.2f}"


def _fmt_ratio(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "--"
    return f"{float(val):.2f}x"


def _fmt_pct(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "--"
    return f"{float(val):.1f}%"


# ─── SPARKLINE ────────────────────────────────────────────────────────────────
def _sparkline(series: pd.Series, color: str, key: str) -> None:
    """Renders a compact sparkline inside a clipped wrapper div."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(series))),
        y=series.values,
        mode="lines",
        line=dict(color=color, width=1.5),
        hoverinfo="skip",
    ))
    fig.update_layout(
        height=40,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True),
        showlegend=False,
    )
    # Wrap in a clipped div so the chart doesn't overflow the card
    st.markdown('<div class="spark-wrap">', unsafe_allow_html=True)
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False, "staticPlot": True},
        key=key,
    )
    st.markdown('</div>', unsafe_allow_html=True)


def _spark_or_dash(series: pd.Series, period: str, quarterly: bool, color: str, key: str):
    """Slice and render sparkline, or show '--' placeholder."""
    spark = slice_sparkline(series, period, quarterly) if not series.empty else pd.Series(dtype=float)
    if len(spark) >= 2:
        _sparkline(spark, color, key=key)
    else:
        st.markdown(
            "<p style='text-align:center;color:#3d4f78;font-size:11px;margin:1px 0 6px;'>--</p>",
            unsafe_allow_html=True,
        )


# ─── CARD HEADER ─────────────────────────────────────────────────────────────
def _card_header(label: str, value_str: str, extra_html: str = "") -> None:
    st.markdown(
        f"""<div style="background:#1b2030;border:1px solid #2c3550;
                border-radius:6px;padding:8px 10px 4px;margin-bottom:0;">
            <div style="font-size:9px;color:#5a6a90;text-transform:uppercase;
                letter-spacing:1px;margin-bottom:3px;">{label}</div>
            <div style="font-size:13px;font-weight:700;color:#dce6f5;
                font-family:monospace;">{value_str}</div>
            {extra_html}
        </div>""",
        unsafe_allow_html=True,
    )


# ─── INDICATOR CELL ───────────────────────────────────────────────────────────
def _cell(label, value_str, series, period, quarterly, color, key):
    _card_header(label, value_str)
    _spark_or_dash(series, period, quarterly, color, key)


# ─── PRICE CELL ───────────────────────────────────────────────────────────────
def _price_cell(ticker, price_data, price_series, period, quarterly):
    up        = price_data["up"]
    pct       = price_data["pct"]
    arrow     = "▲" if up else "▼"
    chg_color = "#4fc98e" if up else "#f05a3d"
    price_val = price_data["price"]
    price_str = f"${price_val:.2f}" if price_val else "--"
    pct_str   = f"{arrow} {abs(pct):.2f}%" if price_val else ""
    spark_color = "#4fc98e" if up else "#f05a3d"

    st.markdown(
        f"""<div style="background:#1b2030;border:1px solid #2c3550;
                border-radius:6px;padding:8px 10px 4px;margin-bottom:0;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">
                <span style="font-size:9px;color:#5a6a90;text-transform:uppercase;letter-spacing:1px;">Price</span>
                <span style="font-size:9px;font-weight:600;color:{chg_color};">{pct_str}</span>
            </div>
            <div style="font-size:13px;font-weight:700;color:#dce6f5;font-family:monospace;">{price_str}</div>
        </div>""",
        unsafe_allow_html=True,
    )
    _spark_or_dash(price_series, period, quarterly, spark_color, f"spark_price_{ticker}_{period}")


# ─── TICKER CARD ──────────────────────────────────────────────────────────────
def _ticker_card(ticker: str, color: str, period: str, quarterly: bool) -> None:
    financials = fetch_financials(ticker, quarterly=quarterly)
    price_data = get_current_price_data(ticker)
    pe_val, pb_val = get_pe_pb(ticker)

    roe_val = financials["roe"].iloc[-1]          if not financials["roe"].empty          else None
    rev_val = financials["revenue"].iloc[-1]       if not financials["revenue"].empty       else None
    nd_val  = financials["net_debt_ebitda"].iloc[-1] if not financials["net_debt_ebitda"].empty else None

    # Ticker header
    st.markdown(
        f"""<div style="font-family:monospace;font-size:14px;font-weight:700;
                color:{color};padding:4px 0 8px;
                border-bottom:1px solid #2c3550;margin-bottom:10px;">
            {ticker}
        </div>""",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        _price_cell(
            ticker=ticker,
            price_data=price_data,
            price_series=financials.get("price", pd.Series(dtype=float)),
            period=period,
            quarterly=quarterly,
        )
        _cell("P/L",           _fmt_ratio(pe_val),   financials.get("pl",              pd.Series(dtype=float)), period, quarterly, color, f"spark_pl_{ticker}_{period}")
        _cell("Net Debt/EBITDA", _fmt_ratio(nd_val), financials.get("net_debt_ebitda", pd.Series(dtype=float)), period, quarterly, color, f"spark_nd_{ticker}_{period}")

    with col2:
        _cell("ROE",     _fmt_pct(roe_val),     financials.get("roe",     pd.Series(dtype=float)), period, quarterly, color, f"spark_roe_{ticker}_{period}")
        _cell("Revenue", _fmt_currency(rev_val), financials.get("revenue", pd.Series(dtype=float)), period, quarterly, color, f"spark_rev_{ticker}_{period}")
        _cell("P/VP",    _fmt_ratio(pb_val),     financials.get("pvp",     pd.Series(dtype=float)), period, quarterly, color, f"spark_pvp_{ticker}_{period}")


# ─── MAIN RENDER ──────────────────────────────────────────────────────────────
def render_indicators(tickers: list[str], period: str, quarterly: bool = False) -> None:
    _inject_css()

    col_title, col_toggle = st.columns([5, 2])
    with col_title:
        st.markdown("### Key Indicators")
    with col_toggle:
        freq      = st.radio("freq", options=["Annual", "Quarterly"], horizontal=True, label_visibility="collapsed")
        quarterly = freq == "Quarterly"

    if not tickers:
        st.info("Select tickers in the sidebar to see indicators.")
        return

    n_cols = min(len(tickers), 4)
    cols   = st.columns(n_cols)

    for i, ticker in enumerate(tickers):
        color = TICKER_COLORS[i % len(TICKER_COLORS)]
        with cols[i % n_cols]:
            with st.container(border=True):
                _ticker_card(ticker=ticker, color=color, period=period, quarterly=quarterly)