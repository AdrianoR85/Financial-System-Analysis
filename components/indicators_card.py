import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from utils.indicators import (
    fetch_financials,
    fetch_ticker_info,
    get_current_price_data,
    slice_sparkline,
)

# ─── COLORS ───────────────────────────────────────────────────────────────────
TICKER_COLORS = [
    "#4f8ef7", "#f75f4f", "#4fc98e", "#f7c74f",
    "#c44fff", "#ff914f", "#4ff7f0", "#f74fa0",
]


# ─── SPARKLINE ────────────────────────────────────────────────────────────────
def _sparkline(series: pd.Series, color: str, key: str) -> None:
    """
    Renders a minimal sparkline using st.plotly_chart.
    Contained in a div with fixed height to prevent it from 'floating'.
    """
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(series))),   # use integer index to avoid tz issues
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
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False, "staticPlot": True},
        key=key,
    )


# ─── FORMATTERS ───────────────────────────────────────────────────────────────
def _fmt_currency(val: float) -> str:
    import math
    if val is None or math.isnan(val):
        return "--"
    if abs(val) >= 1e9:
        return f"${val/1e9:.1f}B"
    if abs(val) >= 1e6:
        return f"${val/1e6:.1f}M"
    if abs(val) >= 1e3:
        return f"${val/1e3:.1f}K"
    return f"${val:.2f}"


def _fmt_ratio(val: float) -> str:
    import math
    if val is None or math.isnan(val):
        return "--"
    return f"{val:.2f}x"


def _fmt_pct(val: float) -> str:
    import math
    if val is None or math.isnan(val):
        return "--"
    return f"{val:.1f}%"


# ─── INDICATOR CELL ───────────────────────────────────────────────────────────
def _cell(
    label: str,
    value_str: str,
    series: pd.Series,
    period: str,
    quarterly: bool,
    color: str,
    key: str,
    extra_html: str = "",   # optional extra line below value (e.g. % change)
) -> None:
    """
    Renders one indicator cell:
      - Dark background card with label + value
      - Optional extra HTML (e.g. % change for price)
      - Sparkline below if >= 2 data points, else '--'

    Everything is inside st.container() to keep the sparkline anchored.
    """
    spark = slice_sparkline(series, period, quarterly) if not series.empty else pd.Series(dtype=float)

    # ── Header block ──────────────────────────────────────────────────────────
    st.markdown(
        f"""
        <div style="background:#1b2030;border:1px solid #2c3550;
                    border-radius:6px;padding:8px 10px 6px;margin-bottom:0px;">
            <div style="font-size:9px;color:#5a6a90;text-transform:uppercase;
                        letter-spacing:1px;margin-bottom:3px;">{label}</div>
            <div style="font-size:13px;font-weight:700;color:#dce6f5;
                        font-family:monospace;">{value_str}</div>
            {extra_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Sparkline or placeholder ───────────────────────────────────────────────
    if len(spark) >= 2:
        _sparkline(spark, color, key=key)
    else:
        st.markdown(
            "<p style='text-align:center;color:#3d4f78;font-size:11px;"
            "margin:2px 0 8px;'>--</p>",
            unsafe_allow_html=True,
        )


# ─── TICKER CARD ──────────────────────────────────────────────────────────────
def _ticker_card(ticker: str, color: str, period: str, quarterly: bool) -> None:
    """
    Renders a full indicator card for one ticker with 6 indicators in a 2-col grid.
    """
    financials = fetch_financials(ticker, quarterly=quarterly)
    info       = fetch_ticker_info(ticker)
    price_data = get_current_price_data(ticker)

    # ── Current values ─────────────────────────────────────────────────────────
    # P/L and P/VP: use trailing values from info (more reliable than calculated)
    pl_val   = info.get("trailingPE")
    pvp_val  = info.get("priceToBook")
    roe_val  = financials["roe"].iloc[-1]  if not financials["roe"].empty  else None
    rev_val  = financials["revenue"].iloc[-1] if not financials["revenue"].empty else None
    nd_val   = financials["net_debt_ebitda"].iloc[-1] if not financials["net_debt_ebitda"].empty else None

    # Build P/L and P/VP sparklines from financials (calculated historically)
    # Fall back to empty if not available
    pl_series  = financials.get("pl",  pd.Series(dtype=float))
    pvp_series = financials.get("pvp", pd.Series(dtype=float))

    # ── Ticker header ──────────────────────────────────────────────────────────
    st.markdown(
        f"""
        <div style="font-family:monospace;font-size:14px;font-weight:700;
                    color:{color};padding:4px 0 8px;
                    border-bottom:1px solid #2c3550;margin-bottom:10px;">
            {ticker}
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    # ── Price cell: label + pct on same row, value below ─────────────────────
    up        = price_data["up"]
    pct       = price_data["pct"]
    arrow     = "▲" if up else "▼"
    chg_color = "#4fc98e" if up else "#f05a3d"
    price_str = f"${price_data['price']:.2f}" if price_data["price"] else "--"
    pct_str   = f"{arrow} {abs(pct):.2f}%" if price_data["price"] else ""
    price_spark_color = "#4fc98e" if up else "#f05a3d"

    with col1:
        # Render price cell manually so label and pct share the same row
        st.markdown(
            f"""
            <div style="background:#1b2030;border:1px solid #2c3550;
                        border-radius:6px;padding:8px 10px 6px;margin-bottom:0px;">
                <div style="display:flex;justify-content:space-between;
                            align-items:center;margin-bottom:3px;">
                    <span style="font-size:9px;color:#5a6a90;
                                 text-transform:uppercase;letter-spacing:1px;">
                        Price
                    </span>
                    <span style="font-size:9px;font-weight:600;color:{chg_color};">
                        {pct_str}
                    </span>
                </div>
                <div style="font-size:13px;font-weight:700;color:#dce6f5;
                            font-family:monospace;">{price_str}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        price_spark = slice_sparkline(
            financials.get("price", pd.Series(dtype=float)), period, quarterly
        )
        if len(price_spark) >= 2:
            _sparkline(price_spark, price_spark_color, key=f"spark_price_{ticker}_{period}")
        else:
            st.markdown(
                "<p style='text-align:center;color:#3d4f78;font-size:11px;"
                "margin:2px 0 8px;'>--</p>",
                unsafe_allow_html=True,
            )
        _cell(
            label="P/L",
            value_str=_fmt_ratio(pl_val) if pl_val else "--",
            series=pl_series,
            period=period,
            quarterly=quarterly,
            color=color,
            key=f"spark_pl_{ticker}_{period}",
        )
        _cell(
            label="Net Debt/EBITDA",
            value_str=_fmt_ratio(nd_val) if nd_val is not None else "--",
            series=financials.get("net_debt_ebitda", pd.Series(dtype=float)),
            period=period,
            quarterly=quarterly,
            color=color,
            key=f"spark_nd_{ticker}_{period}",
        )

    with col2:
        _cell(
            label="ROE",
            value_str=_fmt_pct(roe_val) if roe_val is not None else "--",
            series=financials.get("roe", pd.Series(dtype=float)),
            period=period,
            quarterly=quarterly,
            color=color,
            key=f"spark_roe_{ticker}_{period}",
        )
        _cell(
            label="Revenue",
            value_str=_fmt_currency(rev_val) if rev_val is not None else "--",
            series=financials.get("revenue", pd.Series(dtype=float)),
            period=period,
            quarterly=quarterly,
            color=color,
            key=f"spark_rev_{ticker}_{period}",
        )
        _cell(
            label="P/VP",
            value_str=_fmt_ratio(pvp_val) if pvp_val else "--",
            series=pvp_series,
            period=period,
            quarterly=quarterly,
            color=color,
            key=f"spark_pvp_{ticker}_{period}",
        )


# ─── MAIN RENDER ──────────────────────────────────────────────────────────────
def render_indicators(
    tickers: list[str],
    period: str,
    quarterly: bool = False,
) -> None:
    """
    Renders the full Key Indicators section.
    One card per ticker in a responsive grid (max 4 columns).
    """

    # ── Header + toggle ───────────────────────────────────────────────────────
    col_title, col_toggle = st.columns([5, 2])
    with col_title:
        st.markdown("### Key Indicators")
    with col_toggle:
        freq      = st.radio(
            "freq",
            options=["Annual", "Quarterly"],
            horizontal=True,
            label_visibility="collapsed",
        )
        quarterly = freq == "Quarterly"

    if not tickers:
        st.info("Select tickers in the sidebar to see indicators.")
        return

    # ── One card per ticker ────────────────────────────────────────────────────
    n_cols = min(len(tickers), 4)
    cols   = st.columns(n_cols)

    for i, ticker in enumerate(tickers):
        color = TICKER_COLORS[i % len(TICKER_COLORS)]
        with cols[i % n_cols]:
            # Each card in its own styled container
            with st.container(border=True):
                _ticker_card(
                    ticker=ticker,
                    color=color,
                    period=period,
                    quarterly=quarterly,
                )