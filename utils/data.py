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
    col_map    = {c.lower(): c for c in df.columns}
    ticker_col = col_map.get("symbol") or col_map.get("ticker")
    if ticker_col is None:
        st.error("CSV must have a column named 'Symbol' or 'Ticker'.")
        st.stop()
    df = df.rename(columns={ticker_col: "Ticker"})
    df["Ticker"] = df["Ticker"].str.strip().str.upper()
    return df


def _yf_download(ticker: str, period: str, interval: str) -> "pd.DataFrame | None":
    """
    Download helper that handles both old and new yfinance APIs.
    Returns a flat DataFrame or None.
    """
    raw = None
    # Try new API first (yfinance >= 0.2.40)
    try:
        raw = yf.download(
            ticker, period=period, interval=interval,
            auto_adjust=True, progress=False, multi_level_index=False,
        )
    except TypeError:
        pass

    # Fallback to old API
    if raw is None or raw.empty:
        try:
            raw = yf.download(
                ticker, period=period, interval=interval,
                auto_adjust=True, progress=False,
            )
        except Exception:
            return None

    if raw is None or raw.empty:
        return None

    # Flatten MultiIndex columns
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]

    return raw


def _download_single(ticker: str, period: str, interval: str) -> "pd.Series | None":
    """
    Downloads Close prices for a single ticker.
    Returns a named pd.Series or None.
    """
    raw = _yf_download(ticker, period, interval)
    if raw is None:
        return None

    for col in ["Close", "close", "Adj Close"]:
        if col in raw.columns:
            s = raw[col]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            s = s.dropna()
            return s.rename(ticker) if not s.empty else None

    return None


@st.cache_data(ttl=300)
def fetch_intraday(tickers: list[str]) -> pd.DataFrame:
    """
    Downloads intraday (5min) data.
    Tries period='1d' first; falls back to '2d' if empty (Streamlit Cloud issue).
    Cached for 5 minutes.
    """
    if not tickers:
        return pd.DataFrame()

    series_list = []
    for ticker in tickers:
        s = _download_single(ticker, period="1d", interval="5m")
        if s is None or s.empty:
            # Fallback: 2d window catches today's data even with tz edge cases
            s = _download_single(ticker, period="2d", interval="5m")
        if s is not None and not s.empty:
            series_list.append(s)

    if not series_list:
        return pd.DataFrame()

    return pd.concat(series_list, axis=1).dropna(how="all")


@st.cache_data(ttl=300)
def fetch_prices(tickers: list[str], period: str, interval: str = "1d") -> pd.DataFrame:
    """
    Downloads closing prices for a given period and interval.
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