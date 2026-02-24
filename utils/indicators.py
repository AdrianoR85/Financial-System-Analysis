import pandas as pd
import yfinance as yf
import streamlit as st

# ─── PERIOD → quarters/years to look back ─────────────────────────────────────
SPARKLINE_PERIODS = {
    "1D":  1,
    "5D":  1,
    "10D": 1,
    "1M":  1,
    "3M":  1,
    "6M":  2,
    "1Y":  4,
    "5Y":  5,
    "10Y": 10,
}


@st.cache_data(ttl=3600)
def fetch_ticker_info(ticker: str) -> dict:
    """
    Fetches the general info dict for a ticker via yfinance.
    Tries multiple approaches since .info can fail on Streamlit Cloud.
    """
    try:
        t    = yf.Ticker(ticker)
        info = t.info or {}
        # Enrich with fast_info if currentPrice is missing
        if not (info.get("currentPrice") or info.get("regularMarketPrice")):
            try:
                fi = t.fast_info
                if fi:
                    info.setdefault("currentPrice",  getattr(fi, "last_price",      None))
                    info.setdefault("previousClose", getattr(fi, "previous_close",  None))
            except Exception:
                pass
        return info
    except Exception:
        return {}


@st.cache_data(ttl=300)
def _fetch_last_price_via_download(ticker: str) -> dict:
    """
    Fetches current price via yf.download — reliable fallback for Streamlit Cloud.
    """
    result = {"price": 0.0, "prev": 0.0, "change": 0.0, "pct": 0.0, "up": True}
    try:
        for kwargs in [
            {"multi_level_index": False},   # yfinance >= 0.2.40
            {},                             # older yfinance
        ]:
            try:
                raw = yf.download(
                    ticker, period="5d", interval="1d",
                    auto_adjust=True, progress=False, **kwargs,
                )
                break
            except TypeError:
                raw = None

        if raw is None or raw.empty:
            return result

        # Flatten MultiIndex if present
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0] for c in raw.columns]

        closes = raw["Close"].dropna() if "Close" in raw.columns else pd.Series(dtype=float)
        if len(closes) >= 2:
            result["price"]  = float(closes.iloc[-1])
            result["prev"]   = float(closes.iloc[-2])
            result["change"] = result["price"] - result["prev"]
            result["pct"]    = result["change"] / result["prev"] * 100 if result["prev"] else 0.0
            result["up"]     = result["change"] >= 0
        elif len(closes) == 1:
            result["price"] = float(closes.iloc[0])
    except Exception:
        pass
    return result


@st.cache_data(ttl=3600)
def fetch_financials(ticker: str, quarterly: bool = False) -> dict[str, pd.Series]:
    """
    Fetches historical financial statements for a ticker via yfinance.
    Returns a dict with Series for each indicator we track.
    """
    result = {
        "roe":             pd.Series(dtype=float),
        "pl":              pd.Series(dtype=float),
        "revenue":         pd.Series(dtype=float),
        "net_debt_ebitda": pd.Series(dtype=float),
        "pvp":             pd.Series(dtype=float),
        "price":           pd.Series(dtype=float),
    }

    try:
        t = yf.Ticker(ticker)

        if quarterly:
            income  = t.quarterly_income_stmt
            balance = t.quarterly_balance_sheet
        else:
            income  = t.income_stmt
            balance = t.balance_sheet

        def _get_row(df: pd.DataFrame, *keys) -> pd.Series:
            if df is None or df.empty:
                return pd.Series(dtype=float)
            for key in keys:
                if key in df.index:
                    return df.loc[key].sort_index()
            return pd.Series(dtype=float)

        # Revenue
        revenue = _get_row(income, "Total Revenue", "Revenue", "Net Revenue")
        if not revenue.empty:
            result["revenue"] = revenue

        # ROE = Net Income / Equity
        net_income = _get_row(income, "Net Income", "Net Income Common Stockholders")
        equity     = _get_row(balance, "Stockholders Equity", "Total Stockholder Equity",
                              "Common Stock Equity")
        if not net_income.empty and not equity.empty:
            ni, eq = net_income.align(equity, join="inner")
            roe    = (ni / eq * 100).replace([float("inf"), float("-inf")], pd.NA)
            result["roe"] = roe.dropna()

        # EBITDA proxy
        ebitda = _get_row(income, "EBITDA", "Normalized EBITDA")
        if ebitda.empty:
            ebitda = _get_row(income, "Operating Income", "EBIT")

        # Net Debt / EBITDA
        total_debt = _get_row(balance, "Total Debt", "Long Term Debt")
        cash       = _get_row(balance, "Cash And Cash Equivalents",
                              "Cash Cash Equivalents And Short Term Investments")
        if not total_debt.empty and not cash.empty and not ebitda.empty:
            debt, csh = total_debt.align(cash, join="inner")
            net_debt  = debt - csh
            nd, eb    = net_debt.align(ebitda, join="inner")
            nd_ebitda = (nd / eb).replace([float("inf"), float("-inf")], pd.NA)
            result["net_debt_ebitda"] = nd_ebitda.dropna()

        # Price history (10y daily)
        hist = t.history(period="10y", interval="1d", auto_adjust=True)
        if not hist.empty and "Close" in hist.columns:
            price = hist["Close"]
            if price.index.tz is not None:
                price.index = price.index.tz_localize(None)
            result["price"] = price

        # Shares outstanding
        shares_series = _get_row(balance, "Ordinary Shares Number", "Share Issued")

        # P/L (P/E) sparkline — price / EPS per reporting period
        if not net_income.empty and not shares_series.empty and not result["price"].empty:
            ni, sh = net_income.align(shares_series, join="inner")
            pl_vals = {}
            for date in ni.index:
                ni_val = ni[date]
                sh_val = sh[date]
                if pd.isna(ni_val) or pd.isna(sh_val) or sh_val == 0:
                    continue
                eps           = ni_val / sh_val
                price_on_date = result["price"].asof(date)
                if pd.notna(price_on_date) and eps != 0:
                    pl_vals[date] = price_on_date / eps
            if pl_vals:
                result["pl"] = pd.Series(pl_vals).sort_index()

        # P/VP (P/B) sparkline — price / BVPS per reporting period
        if not equity.empty and not shares_series.empty and not result["price"].empty:
            eq, sh = equity.align(shares_series, join="inner")
            pvp_vals = {}
            for date in eq.index:
                eq_val = eq[date]
                sh_val = sh[date]
                if pd.isna(eq_val) or pd.isna(sh_val) or sh_val == 0:
                    continue
                bvps          = eq_val / sh_val
                price_on_date = result["price"].asof(date)
                if pd.notna(price_on_date) and bvps != 0:
                    pvp_vals[date] = price_on_date / bvps
            if pvp_vals:
                result["pvp"] = pd.Series(pvp_vals).sort_index()

    except Exception:
        pass

    return result


def get_current_price_data(ticker: str) -> dict:
    """
    Returns current price and direction vs previous close.
    Tries .info first, then falls back to yf.download (more reliable on Cloud).
    """
    info    = fetch_ticker_info(ticker)
    current = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
    prev    = info.get("previousClose") or info.get("regularMarketPreviousClose") or 0.0

    if current:
        change = current - prev
        pct    = (change / prev * 100) if prev else 0.0
        return {
            "price":  float(current),
            "prev":   float(prev),
            "change": float(change),
            "pct":    float(pct),
            "up":     change >= 0,
        }

    # Fallback to download-based approach
    return _fetch_last_price_via_download(ticker)


def get_pe_pb(ticker: str) -> tuple:
    """
    Returns (trailing_pe, price_to_book).
    Tries .info first, then falls back to calculated sparkline values.
    """
    info   = fetch_ticker_info(ticker)
    pe_val = info.get("trailingPE")
    pb_val = info.get("priceToBook")

    # Fallback: use last value from calculated sparklines
    if not pe_val or not pb_val:
        try:
            financials = fetch_financials(ticker)
            if not pe_val and not financials["pl"].empty:
                pe_val = float(financials["pl"].iloc[-1])
            if not pb_val and not financials["pvp"].empty:
                pb_val = float(financials["pvp"].iloc[-1])
        except Exception:
            pass

    return (pe_val or None, pb_val or None)


def slice_sparkline(series: pd.Series, period: str, quarterly: bool) -> pd.Series:
    """
    Slices a financial Series to the number of data points appropriate
    for the selected sidebar period.
    """
    if series.empty:
        return series

    n = SPARKLINE_PERIODS.get(period, 1)
    if not quarterly:
        n = max(n, 2) if period not in ("1D", "5D", "10D", "1M", "3M") else 1

    sliced = series.sort_index().tail(n)
    return sliced if len(sliced) >= 2 else pd.Series(dtype=float)