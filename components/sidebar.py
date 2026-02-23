import streamlit as st
from utils.data import load_tickers, fetch_prices, best_worst, PERIOD_MAP

# ─── Best/worst needs enough daily data points to compute a return.
# For very short periods (1D, 5D), yfinance may return only 1-2 daily rows,
# so we map them to a wider window for the best/worst calculation only.
_BEST_WORST_PERIOD = {
    "1D":  "1mo",   # Need at least 2 daily data points
    "5D":  "1mo",
    "10D": "1mo",
    "1M":  "1mo",
    "3M":  "3mo",
    "6M":  "6mo",
    "1Y":  "1y",
    "5Y":  "5y",
    "10Y": "10y",
}
_BEST_WORST_ROWS = {
    "1D":  2,
    "5D":  5,
    "10D": 10,
    "1M":  21,
    "3M":  63,
    "6M":  126,
    "1Y":  252,
    "5Y":  1260,
    "10Y": 2520,
}

# ─── PERIOD BUTTON ROWS ───────────────────────────────────────────────────────
# Groups the period labels into rows of 3 for the grid layout
PERIOD_ROWS = [
    ["1D",  "5D",  "10D"],
    ["1M",  "3M",  "6M"],
    ["1Y",  "5Y",  "10Y"],
]


def render_sidebar() -> tuple[list[str], str]:
    """
    Renders the full sidebar:
      - Logo
      - Ticker multiselect (loaded from CSV)
      - Period selector (compact button grid)
      - Best / Worst stock cards

    Returns:
        selected_tickers (list[str]): tickers chosen by the user
        selected_period  (str):       active period label, e.g. "1M"
    """
    with st.sidebar:

        # ── Logo ─────────────────────────────────────────────────────────────
        st.markdown("## 📈 MY LOGO")
        st.divider()

        # ── Ticker selector ───────────────────────────────────────────────────
        st.markdown("**Tickers**")

        sp500_df = load_tickers("data/sp500.csv")
        all_tickers = sp500_df["Ticker"].tolist()

        # Default to first two available tickers
        default = [t for t in ["AAPL", "MSFT"] if t in all_tickers] or all_tickers[:2]

        selected_tickers: list[str] = st.multiselect(
            label="Tickers",
            options=all_tickers,
            default=default,
            placeholder="Search ticker...",
            label_visibility="collapsed",
        )

        # ── Period selector ───────────────────────────────────────────────────
        # Compact CSS to reduce button size and spacing
        st.markdown(
            """
            <style>
                /* Shrink sidebar buttons */
                section[data-testid="stSidebar"] .stButton > button {
                    padding: 2px 2px !important;
                    font-size: 8px !important;
                    min-height: 0 !important;
                    height: 24px !important;
                    line-height: 1 !important;
                }
                /* Reduce gaps between sidebar elements */
                section[data-testid="stSidebar"] .block-container {
                    gap: 4px !important;
                }
                section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
                    gap: 4px !important;
                }
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            "<p style='margin:20px 0 20px;font-size:16px;font-weight:600;'>Period</p>",
            unsafe_allow_html=True,
        )

        # Initialize period in session state
        if "period" not in st.session_state:
            st.session_state["period"] = "1M"

        # Render 3×3 button grid
        for row in PERIOD_ROWS:
            cols = st.columns(3)
            for col, period in zip(cols, row):
                with col:
                    is_active = st.session_state["period"] == period
                    if st.button(
                        period,
                        key=f"period_{period}",
                        type="primary" if is_active else "secondary",
                        use_container_width=True,
                    ):
                        st.session_state["period"] = period
                        st.rerun()

        selected_period: str = st.session_state["period"]

        # ── Best / Worst cards ────────────────────────────────────────────────
        st.markdown(
            "<p style='margin:20px 0 20px;font-size:16px;font-weight:500;'>Performance</p>",
            unsafe_allow_html=True,
        )

        if selected_tickers:
            bw_period = _BEST_WORST_PERIOD[selected_period]
            bw_rows   = _BEST_WORST_ROWS[selected_period]
            prices = fetch_prices(selected_tickers, bw_period, interval="1d")
            # Trim to the correct number of trading days for the selected period
            if not prices.empty:
                prices = prices.tail(bw_rows)
            best, worst = best_worst(prices)
        else:
            best, worst = "—", "—"

        col_b, col_w = st.columns(2)

        with col_b:
            st.markdown(
                f"""
                <div style="background:#1a2e1a;border:1px solid #2d5a2d;border-radius:8px;
                            padding:8px 6px;text-align:center;">
                    <div style="font-size:9px;color:#5a8a5a;
                                text-transform:uppercase;letter-spacing:1px;">
                        Best Stock
                    </div>
                    <div style="font-size:18px;font-weight:600;color:#4fc98e;
                                font-family:monospace;margin-top:2px;">
                        {best}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with col_w:
            st.markdown(
                f"""
                <div style="background:#2e1a1a;border:1px solid #5a2d2d;border-radius:8px;
                            padding:8px 6px;text-align:center;">
                    <div style="font-size:9px;color:#8a5a5a;
                                text-transform:uppercase;letter-spacing:1px;">
                        Worst Stock
                    </div>
                    <div style="font-size:18px;font-weight:600;color:#f05a3d;
                                font-family:monospace;margin-top:2px;">
                        {worst}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    return selected_tickers, selected_period
