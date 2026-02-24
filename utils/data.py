import pandas as pd
import yfinance as yf
import streamlit as st

# ─── PERIOD MAPPING ───────────────────────────────────────────────────────────
PERIOD_MAP = {
    "1D":  "1d",
    "5D":  "5d",
    "10D": "10d",
    "1M":  "1mo",
    "3M":  "3mo",
    "6M":  "6mo",
    "1Y":  "1y",
    "5Y":  "5y",
    "10Y": "10y",
}

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
    """Loads the S&P 500 ticker list from a local CSV file."""
    df = pd.read_csv(path)
    col_map = {c.lower(): c for c in df.columns}
    ticker_col = col_map.get("symbol") or col_map.get("ticker")

    if ticker_col is None:
        st.error("CSV must have a column named 'Symbol' or 'Ticker'.")
        st.stop()

    df = df.rename(columns={ticker_col: "Ticker"})
    df["Ticker"] = df["Ticker"].str.strip().str.upper()
    return df


def _download_single(ticker: str, period: str, interval: str) -> "pd.Series | None":
    """
    Downloads Close prices for a single ticker via yfinance.
    Tries multiple approaches to handle yfinance API variations.
    Returns a named pd.Series or None if no data is available.
    """
    raw = None

    # Attempt 1: modern API with multi_level_index=False
    try:
        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            multi_level_index=False,
        )
    except Exception:
        pass

    # Attempt 2: legacy API without multi_level_index
    if raw is None or raw.empty:
        try:
            raw = yf.download(
                ticker,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
            )
        except Exception:
            return None

    if raw is None or raw.empty:
        return None

    # Flatten MultiIndex columns if present
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [
            col[0] if isinstance(col, tuple) else col
            for col in raw.columns
        ]

    # Try to get Close column
    for col_name in ["Close", "close", "Adj Close"]:
        if col_name in raw.columns:
            series = raw[col_name]
            if isinstance(series, pd.DataFrame):
                series = series.iloc[:, 0]
            return series.rename(ticker)

    return None


@st.cache_data(ttl=300)
def fetch_intraday(tickers: list[str]) -> pd.DataFrame:
    """
    Downloads today's intraday data at 5-minute intervals.
    Falls back to 2-day period if 1d returns empty (common on Streamlit Cloud).
    Cached for 5 minutes.
    """
    if not tickers:
        return pd.DataFrame()

    series_list = []
    for ticker in tickers:
        s = _download_single(ticker, period="1d", interval="5m")
        # Fallback: try 2d if 1d is empty (timezone edge cases on cloud)
        if s is None or s.empty:
            s = _download_single(ticker, period="2d", interval="5m")
        if s is not None and not s.empty:
            series_list.append(s)

    if not series_list:
        return pd.DataFrame()

    return pd.concat(series_list, axis=1).dropna(how="all")


@st.cache_data(ttl=300)
def fetch_prices(tickers: list[str], period: str, interval: str = "1d") -> pd.DataFrame:
    """
    Downloads closing prices for a given period and interval via yfinance.
    Cached for 5 minutes.
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
    """Returns (best, worst) ticker based on period return."""
    if prices.empty or prices.shape[1] < 1:
        return "—", "—"

    returns = (prices.iloc[-1] / prices.iloc[0] - 1).dropna()

    if returns.empty:
        return "—", "—"

    return returns.idxmax(), returns.idxmin()