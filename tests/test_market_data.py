from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import market_data


def _fake_history(n=250, start_price=100.0):
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    closes = [start_price + i * 0.5 for i in range(n)]
    data = {
        "Open": closes,
        "High": [c + 1 for c in closes],
        "Low": [c - 1 for c in closes],
        "Close": closes,
        "Volume": [1_000_000 for _ in range(n)],
    }
    return pd.DataFrame(data, index=dates)


def test_get_quote_returns_last_close():
    fake_hist = _fake_history(n=5)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = fake_hist
    with patch("market_data.yf.Ticker", return_value=mock_ticker):
        price = market_data.get_quote("TEST")
    assert price == fake_hist["Close"].iloc[-1]


def test_get_quote_falls_back_past_nan_latest_bar():
    fake_hist = _fake_history(n=5)
    fake_hist.loc[fake_hist.index[-1], ["Open", "High", "Low", "Close"]] = float("nan")
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = fake_hist
    with patch("market_data.yf.Ticker", return_value=mock_ticker):
        price = market_data.get_quote("TEST")
    assert price == fake_hist["Close"].iloc[-2]


def test_get_quote_raises_when_all_closes_nan():
    fake_hist = _fake_history(n=3)
    fake_hist["Close"] = float("nan")
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = fake_hist
    with patch("market_data.yf.Ticker", return_value=mock_ticker):
        with pytest.raises(ValueError):
            market_data.get_quote("TEST")


def test_get_history_drops_nan_close_rows():
    fake_hist = _fake_history(n=5)
    fake_hist.loc[fake_hist.index[-1], ["Open", "High", "Low", "Close"]] = float("nan")
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = fake_hist
    with patch("market_data.yf.Ticker", return_value=mock_ticker):
        records = market_data.get_history("TEST")
    assert len(records) == 4
    assert records[-1]["close"] == fake_hist["Close"].iloc[-2]


def test_get_quote_raises_on_empty_history():
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    with patch("market_data.yf.Ticker", return_value=mock_ticker):
        with pytest.raises(ValueError):
            market_data.get_quote("BADTICKER")


def test_get_history_returns_records():
    fake_hist = _fake_history(n=3)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = fake_hist
    with patch("market_data.yf.Ticker", return_value=mock_ticker):
        records = market_data.get_history("TEST")
    assert len(records) == 3
    assert records[0]["close"] == fake_hist["Close"].iloc[0]
    assert set(records[0].keys()) == {"date", "open", "high", "low", "close", "volume"}


def test_get_indicators_full_history_has_all_fields():
    fake_hist = _fake_history(n=250)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = fake_hist
    with patch("market_data.yf.Ticker", return_value=mock_ticker):
        result = market_data.get_indicators("TEST")
    assert result["rsi14"] is not None
    assert result["sma20"] is not None
    assert result["sma50"] is not None
    assert result["sma200"] is not None
    assert result["macd"] is not None
    assert result["volume_trend"] is not None


def test_get_indicators_short_history_omits_long_window_fields():
    fake_hist = _fake_history(n=30)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = fake_hist
    with patch("market_data.yf.Ticker", return_value=mock_ticker):
        result = market_data.get_indicators("NEWISSUE")
    assert result["sma20"] is not None
    assert result["sma50"] is None
    assert result["sma200"] is None


def test_get_fundamentals_maps_fields():
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "currentPrice": 150.0,
        "sector": "Technology",
        "marketCap": 2_000_000_000,
        "trailingPE": 25.5,
        "pegRatio": 1.8,
        "revenueGrowth": 0.12,
        "profitMargins": 0.21,
        "debtToEquity": 45.0,
        "targetMeanPrice": 180.0,
    }
    with patch("market_data.yf.Ticker", return_value=mock_ticker):
        result = market_data.get_fundamentals("TEST")
    assert result["sector"] == "Technology"
    assert result["trailing_pe"] == 25.5


def test_get_fundamentals_raises_when_no_data():
    mock_ticker = MagicMock()
    mock_ticker.info = {}
    with patch("market_data.yf.Ticker", return_value=mock_ticker):
        with pytest.raises(ValueError):
            market_data.get_fundamentals("DELISTED")


def test_get_news_parses_items():
    mock_ticker = MagicMock()
    mock_ticker.news = [
        {
            "content": {
                "title": "Big news",
                "provider": {"displayName": "Reuters"},
                "canonicalUrl": {"url": "http://example.com/a"},
            }
        },
    ]
    with patch("market_data.yf.Ticker", return_value=mock_ticker):
        result = market_data.get_news("TEST")
    assert result[0]["title"] == "Big news"
    assert result[0]["publisher"] == "Reuters"
