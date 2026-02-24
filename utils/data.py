import pandas as pd
import yfinance as yf
import streamlit as st

# ─── PERIOD MAPPING ───────────────────────────────────────────────────────────
PERIOD_MAP = {
    "1D":  "1d",
    "5D":  "5d",
    "10D": "1mo",    # yfinance doesn't support "10d"; use "1mo" which covers ~21 trading days
    "1M":  "1mo",
    "3M":  "3mo",
    "6M":  "6mo",
    "1Y":  "1y",
    "5Y":  "5y",
    "10Y": "10y",
}

# Interval per period: intraday uses 5m, daily/weekly/monthly for longer ranges
INTERVAL_MAP = {
    "1D":  "5m",
    "5D":  "5m",
    "10D": "5m",
    "1M":  "1d",
    "3M":  "1d",
    "6M":  "1d",
    "1Y":  "1d",
    "5Y":  "1wk",
    "10Y": "1mo",
}


@st.cache_data
def load_tickers(path: str = "data/sp500.csv") -> pd.DataFrame:
    """
    Loads the S&P 500 ticker list from a local CSV file.
    Accepts columns named 'Symbol' or 'Ticker' (case-insensitive).
    """
    df = pd.read_csv(path)
    col_map = {c.lower(): c for c in df.columns}
    ticker_col = col_map.get("symbol") or col_map.get("ticker")

    if ticker_col is None:
        st.error("CSV must have a column named 'Symbol' or 'Ticker'.")
        st.stop()

    df = df.rename(columns={ticker_col: "Ticker"})
    df["Ticker"] = df["Ticker"].str.strip().str.upper()
    return df


def _download_single(ticker: str, period: str, interval: str) -> pd.Series | None:
    """
    Downloads Close prices for a single ticker via yfinance.
    Returns a named pd.Series or None if no data is available.
    Handles all known yfinance column structures across versions.
    """
    try:
        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            multi_level_index=False,    # yfinance >= 0.2.40: forces flat columns
        )
    except TypeError:
        # multi_level_index not supported in older versions
        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
        )

    if raw is None or raw.empty:
        return None

    # Flat columns
    if isinstance(raw.columns, pd.Index) and "Close" in raw.columns:
        series = raw["Close"]
        if isinstance(series, pd.Series):
            return series.rename(ticker)

    # MultiIndex fallback
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            series = raw["Close"]
            if isinstance(series, pd.DataFrame):
                series = series.iloc[:, 0]
            return series.rename(ticker)
        if "Close" in raw.columns.get_level_values(1):
            series = raw.xs("Close", axis=1, level=1).iloc[:, 0]
            return series.rename(ticker)

    return None


@st.cache_data(ttl=300)
def fetch_intraday(tickers: list[str]) -> pd.DataFrame:
    """
    Downloads today's intraday data at 5-minute intervals (period='1d').
    Cached for 5 minutes (ttl=300).
    """
    if not tickers:
        return pd.DataFrame()

    series_list = [
        s for ticker in tickers
        if (s := _download_single(ticker, period="1d", interval="5m")) is not None
        and not s.empty
    ]

    if not series_list:
        return pd.DataFrame()

    return pd.concat(series_list, axis=1).dropna(how="all")


@st.cache_data(ttl=300)
def fetch_prices(tickers: list[str], period: str, interval: str = "1d") -> pd.DataFrame:
    """
    Downloads closing prices for a given period and interval via yfinance.
    Cached for 5 minutes (ttl=300).
    """
    if not tickers:
        return pd.DataFrame()

    series_list = [
        s for ticker in tickers
        if (s := _download_single(ticker, period=period, interval=interval)) is not None
        and not s.empty
    ]

    if not series_list:
        return pd.DataFrame()

    return pd.concat(series_list, axis=1).dropna(how="all")


def best_worst(prices: pd.DataFrame) -> tuple[str, str]:
    """
    Returns (best, worst) ticker based on period return:
    (last_price / first_price - 1).
    If only 1 ticker is available, returns (ticker, "—").
    """
    if prices.empty or prices.shape[1] < 1:
        return "—", "—"

    returns = (prices.iloc[-1] / prices.iloc[0] - 1).dropna()

    if returns.empty:
        return "—", "—"

    if len(returns) == 1:
        return returns.index[0], "—"

    return returns.idxmax(), returns.idxmin()
