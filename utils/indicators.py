import pandas as pd
import yfinance as yf
import streamlit as st

# ─── PERIOD → quarters/years to look back ─────────────────────────────────────
# Maps the sidebar period label to how many data points we want in the sparkline.
# Financial data is quarterly or annual, so we map accordingly.
SPARKLINE_PERIODS = {
    "1D":  1,
    "5D":  1,
    "10D": 1,
    "1M":  1,
    "3M":  1,
    "6M":  2,
    "1Y":  4,   # 4 quarters or 1 annual point
    "5Y":  5,   # 5 annual points
    "10Y": 10,
}


@st.cache_data(ttl=3600)
def fetch_ticker_info(ticker: str) -> dict:
    """
    Fetches the general info dict for a ticker via yfinance.
    Contains currentPrice, previousClose, trailingPE, priceToBook, etc.
    Cached for 1 hour (ttl=3600) since this data changes slowly.
    """
    try:
        t = yf.Ticker(ticker)
        return t.info or {}
    except Exception:
        return {}


@st.cache_data(ttl=3600)
def fetch_financials(ticker: str, quarterly: bool = False) -> dict[str, pd.Series]:
    """
    Fetches historical financial statements for a ticker via yfinance.
    Returns a dict with Series for each indicator we track.

    Data sources:
      - income_stmt   → Net Income, Net Revenue
      - balance_sheet → Total Stockholder Equity, Total Debt
      - cashflow      → Operating Cash Flow (used for EBITDA proxy)
      - history       → Price history for P/L and P/VP sparklines

    Args:
        ticker:     Stock ticker symbol
        quarterly:  If True, use quarterly statements; else annual

    Returns dict keys:
        'roe'       → Return on Equity (%) per period
        'pl'        → Price-to-Earnings ratio per period  
        'revenue'   → Net Revenue per period
        'net_debt_ebitda' → Net Debt / EBITDA per period
        'pvp'       → Price-to-Book ratio per period
        'price'     → Daily closing price history
    """
    result = {
        "roe":            pd.Series(dtype=float),
        "pl":             pd.Series(dtype=float),
        "revenue":        pd.Series(dtype=float),
        "net_debt_ebitda": pd.Series(dtype=float),
        "pvp":            pd.Series(dtype=float),
        "price":          pd.Series(dtype=float),
    }

    try:
        t = yf.Ticker(ticker)

        # ── Choose quarterly or annual statements ─────────────────────────────
        if quarterly:
            income  = t.quarterly_income_stmt
            balance = t.quarterly_balance_sheet
            cf      = t.quarterly_cashflow
        else:
            income  = t.income_stmt
            balance = t.balance_sheet
            cf      = t.cashflow

        # ── Helper: safely get a row from a statement ─────────────────────────
        def _get_row(df: pd.DataFrame, *keys) -> pd.Series:
            """Tries multiple key names and returns the first match."""
            if df is None or df.empty:
                return pd.Series(dtype=float)
            for key in keys:
                if key in df.index:
                    return df.loc[key].sort_index()
            return pd.Series(dtype=float)

        # ── Net Revenue ───────────────────────────────────────────────────────
        revenue = _get_row(income, "Total Revenue", "Revenue", "Net Revenue")
        if not revenue.empty:
            result["revenue"] = revenue

        # ── ROE = Net Income / Stockholders Equity ────────────────────────────
        net_income = _get_row(income, "Net Income", "Net Income Common Stockholders")
        equity     = _get_row(balance, "Stockholders Equity", "Total Stockholder Equity",
                              "Common Stock Equity")

        if not net_income.empty and not equity.empty:
            # Align on common dates and calculate ROE (%)
            ni, eq = net_income.align(equity, join="inner")
            roe    = (ni / eq * 100).replace([float("inf"), float("-inf")], pd.NA)
            result["roe"] = roe.dropna()

        # ── EBITDA proxy = Operating Income + D&A ─────────────────────────────
        ebitda = _get_row(income, "EBITDA", "Normalized EBITDA")
        if ebitda.empty:
            # Fallback: Operating Income as EBITDA proxy
            ebitda = _get_row(income, "Operating Income", "EBIT")

        # ── Net Debt = Total Debt - Cash ──────────────────────────────────────
        total_debt  = _get_row(balance, "Total Debt", "Long Term Debt")
        cash        = _get_row(balance, "Cash And Cash Equivalents",
                               "Cash Cash Equivalents And Short Term Investments")

        if not total_debt.empty and not cash.empty and not ebitda.empty:
            debt, csh  = total_debt.align(cash, join="inner")
            net_debt   = debt - csh
            nd, eb     = net_debt.align(ebitda, join="inner")
            nd_ebitda  = (nd / eb).replace([float("inf"), float("-inf")], pd.NA)
            result["net_debt_ebitda"] = nd_ebitda.dropna()

        # ── Price history (for price sparkline) ───────────────────────────────
        hist = t.history(period="10y", interval="1d", auto_adjust=True)
        if not hist.empty and "Close" in hist.columns:
            price = hist["Close"]
            # Remove timezone so asof() can compare with tz-naive statement dates
            if price.index.tz is not None:
                price.index = price.index.tz_localize(None)
            result["price"] = price

        # ── Shares per period from balance sheet ──────────────────────────────
        # "Ordinary Shares Number" gives shares outstanding per reporting date,
        # which is more accurate than a single current value from info.
        shares_series = _get_row(balance, "Ordinary Shares Number", "Share Issued")

        # ── P/L sparkline ─────────────────────────────────────────────────────
        # P/L = Price / EPS,  where EPS = Net Income / Shares per period
        if not net_income.empty and not shares_series.empty and not result["price"].empty:
            # Align net income and shares on common dates
            ni, sh = net_income.align(shares_series, join="inner")
            pl_vals = {}
            for date in ni.index:
                ni_val    = ni[date]
                sh_val    = sh[date]
                if pd.isna(ni_val) or pd.isna(sh_val) or sh_val == 0:
                    continue
                eps_val       = ni_val / sh_val
                price_on_date = result["price"].asof(date)
                if pd.notna(price_on_date) and eps_val != 0:
                    pl_vals[date] = price_on_date / eps_val
            if pl_vals:
                result["pl"] = pd.Series(pl_vals).sort_index()

        # ── P/VP sparkline ────────────────────────────────────────────────────
        # P/VP = Price / BVPS,  where BVPS = Equity / Shares per period
        if not equity.empty and not shares_series.empty and not result["price"].empty:
            eq, sh = equity.align(shares_series, join="inner")
            pvp_vals = {}
            for date in eq.index:
                eq_val  = eq[date]
                sh_val  = sh[date]
                if pd.isna(eq_val) or pd.isna(sh_val) or sh_val == 0:
                    continue
                bvps_val      = eq_val / sh_val
                price_on_date = result["price"].asof(date)
                if pd.notna(price_on_date) and bvps_val != 0:
                    pvp_vals[date] = price_on_date / bvps_val
            if pvp_vals:
                result["pvp"] = pd.Series(pvp_vals).sort_index()

    except Exception:
        pass  # Return whatever was collected; empty Series for failed fields

    return result


def get_current_price_data(ticker: str) -> dict:
    """
    Returns current price and direction vs previous close.

    Returns:
        {
          'price':   float  — current price
          'prev':    float  — previous close
          'change':  float  — absolute change
          'pct':     float  — percent change
          'up':      bool   — True if price >= prev close
        }
    """
    info = fetch_ticker_info(ticker)

    current = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
    prev    = info.get("previousClose") or info.get("regularMarketPreviousClose") or 0.0

    change  = current - prev
    pct     = (change / prev * 100) if prev else 0.0

    return {
        "price":  current,
        "prev":   prev,
        "change": change,
        "pct":    pct,
        "up":     change >= 0,
    }


def slice_sparkline(series: pd.Series, period: str, quarterly: bool) -> pd.Series:
    """
    Slices a financial Series to the number of data points appropriate
    for the selected sidebar period.

    If fewer than 2 points are available after slicing, returns empty Series
    (the UI will show '--' instead of a sparkline).

    Args:
        series:     Full historical Series of the indicator
        period:     Sidebar period label (e.g. '1Y', '5Y')
        quarterly:  Whether data is quarterly or annual

    Returns:
        Sliced Series, or empty Series if insufficient data
    """
    if series.empty:
        return series

    n = SPARKLINE_PERIODS.get(period, 1)

    # Annual data has fewer points — scale accordingly
    if not quarterly:
        # Annual: n already maps to years; for short periods, use at least 2
        n = max(n, 2) if period not in ("1D", "5D", "10D", "1M", "3M") else 1

    sliced = series.sort_index().tail(n)
    return sliced if len(sliced) >= 2 else pd.Series(dtype=float)