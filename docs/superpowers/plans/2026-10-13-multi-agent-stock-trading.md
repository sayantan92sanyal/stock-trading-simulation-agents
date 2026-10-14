# Multi-Agent Paper Trading System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build six Claude Code subagents (boss, technical trader, fundamental trader, retail investor, performance reviewer) that run a paper-trading simulation against real market data, backed by deterministic Python scripts for all money math and data fetching.

**Architecture:** Three independent "trader" subagents each reason in their own style and emit a structured JSON decision list; a "boss" subagent resolves the round's ticker universe, dispatches the traders in parallel, and executes their decisions through a single deterministic ledger script (`scripts/portfolio.py`) so no LLM ever does money arithmetic. A "performance reviewer" subagent runs only on explicit request and appends a dated verdict to a markdown log.

**Tech Stack:** Python 3 (stdlib `argparse`/`json` + `yfinance` for market data), `pytest` for the script test suites, Claude Code project subagents (`.claude/agents/*.md`).

**Spec:** `docs/superpowers/specs/2026-10-13-multi-agent-stock-trading-design.md`

## Global Constraints

- Paper trading only — no real brokerage integration, no real money.
- Data sources: `yfinance` only, no paid API keys.
- $50,000 starting virtual cash per trader agent, equal across all three.
- Trade execution is centralized in `scripts/portfolio.py`; trader agents decide what to do, they never touch the ledger files directly.
- Performance review runs only on explicit user request — never automatically after a trading round.
- Long-only cash equities — no shorting, margin, or options.
- Stock universe is supplied by the user each round (explicit tickers or a sector/theme), never hard-coded into the system.
- Every Bash call from an agent is a fresh shell (no persisted `source activate`), so all script invocations use the venv interpreter directly: `.venv/bin/python3 scripts/<script>.py ...`.

## Review Focus

- Invalid/delisted ticker with no price data → `market_data.py` raises a clear error and `portfolio.py`'s CLI reports it as a clean failure (not a stack trace). Owned by Task 2 and Task 3.
- A trade request with zero or more than one sizing flag (`--shares`/`--cash-amount`/`--pct-cash`) → rejected cleanly, never silently defaulted or crashed. Owned by Task 3.
- Selling a ticker the agent holds zero shares of → rejected via the same "insufficient shares" path as a partial oversell, not a separate crash (e.g. `KeyError`). Owned by Task 3.
- `--cash-amount`/`--pct-cash` sizing that rounds down to 0 shares (e.g. a small cash amount against a high-priced stock) → rejected as an invalid order, never silently executed as a no-op. Owned by Task 3.
- A ticker with too little price history for a longer-window indicator (e.g. SMA200 on a recently-listed stock) → that field comes back `null` instead of crashing the whole `indicators` call. Owned by Task 2.

---

## Task 1: Project scaffolding + pure indicator math

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `.gitignore`
- Create: `scripts/indicators.py`
- Create: `tests/test_indicators.py`

**Interfaces:**
- Produces: `sma(values: list[float], window: int) -> float`, `ema_series(values: list[float], span: int) -> list[float]`, `rsi(values: list[float], period: int = 14) -> float`, `macd(values: list[float], fast=12, slow=26, signal=9) -> dict` (keys `macd`, `signal`, `histogram`), `volume_trend(volumes: list[float], window: int = 20) -> float`. All raise `ValueError` on insufficient input length. Consumed by Task 2.

- [ ] **Step 1: Create directory structure and venv**

```bash
mkdir -p scripts tests data/portfolios data/trades data/performance
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
```

- [ ] **Step 2: Write `requirements.txt`**

```
pytest>=7.4
```

- [ ] **Step 3: Write `pytest.ini`**

```ini
[pytest]
pythonpath = scripts
```

- [ ] **Step 4: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/
```

- [ ] **Step 5: Install dependencies**

```bash
.venv/bin/pip install -r requirements.txt
```

- [ ] **Step 6: Write the failing tests**

Create `tests/test_indicators.py`:

```python
import pytest

import indicators


def test_sma_basic():
    assert indicators.sma([1, 2, 3, 4, 5], 3) == pytest.approx(4.0)


def test_sma_insufficient_values_raises():
    with pytest.raises(ValueError):
        indicators.sma([1, 2], 3)


def test_ema_series_of_constant_values_is_constant():
    values = [10.0] * 40
    result = indicators.ema_series(values, span=12)
    assert result[-1] == pytest.approx(10.0)
    assert all(v == pytest.approx(10.0) for v in result)


def test_rsi_hand_computed_mixed_gains_and_losses():
    # 10 up-days of +2, then 4 down-days of -1, period=14
    prices = [50, 52, 54, 56, 58, 60, 62, 64, 66, 68, 70, 69, 68, 67, 66]
    result = indicators.rsi(prices, period=14)
    # avg_gain = 20/14, avg_loss = 4/14, rs = 5.0, rsi = 100 - 100/6
    assert result == pytest.approx(83.33333333333333)


def test_rsi_all_gains_is_100():
    prices = list(range(100, 115))  # 15 values, 14 pure gains
    assert indicators.rsi(prices, period=14) == pytest.approx(100.0)


def test_rsi_insufficient_values_raises():
    with pytest.raises(ValueError):
        indicators.rsi([1, 2, 3], period=14)


def test_macd_of_constant_series_is_zero():
    values = [10.0] * 40
    result = indicators.macd(values)
    assert result["macd"] == pytest.approx(0.0)
    assert result["signal"] == pytest.approx(0.0)
    assert result["histogram"] == pytest.approx(0.0)


def test_macd_of_uptrend_is_positive():
    values = [float(v) for v in range(1, 41)]
    result = indicators.macd(values)
    assert result["macd"] > 0


def test_macd_insufficient_values_raises():
    with pytest.raises(ValueError):
        indicators.macd([1.0] * 10)


def test_volume_trend_hand_computed():
    volumes = [100] * 20 + [150]
    assert indicators.volume_trend(volumes, window=20) == pytest.approx(1.5)


def test_volume_trend_zero_baseline_raises():
    volumes = [0] * 20 + [50]
    with pytest.raises(ValueError):
        indicators.volume_trend(volumes, window=20)


def test_volume_trend_insufficient_values_raises():
    with pytest.raises(ValueError):
        indicators.volume_trend([100] * 5, window=20)
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_indicators.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indicators'`

- [ ] **Step 8: Write the implementation**

Create `scripts/indicators.py`:

```python
"""Pure, deterministic technical indicator calculations. No I/O, no network."""


def sma(values, window):
    if len(values) < window:
        raise ValueError(f"need at least {window} values, got {len(values)}")
    return sum(values[-window:]) / window


def ema_series(values, span):
    if not values:
        raise ValueError("values must not be empty")
    alpha = 2 / (span + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        raise ValueError(f"need at least {period + 1} values, got {len(values)}")
    window = values[-(period + 1):]
    gains = []
    losses = []
    for prev, curr in zip(window[:-1], window[1:]):
        change = curr - prev
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-change)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal:
        raise ValueError(f"need at least {slow + signal} values, got {len(values)}")
    fast_ema = ema_series(values, fast)
    slow_ema = ema_series(values, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = ema_series(macd_line, signal)
    return {
        "macd": macd_line[-1],
        "signal": signal_line[-1],
        "histogram": macd_line[-1] - signal_line[-1],
    }


def volume_trend(volumes, window=20):
    if len(volumes) < window + 1:
        raise ValueError(f"need at least {window + 1} values, got {len(volumes)}")
    baseline = sum(volumes[-(window + 1):-1]) / window
    if baseline == 0:
        raise ValueError("baseline average volume is zero")
    return volumes[-1] / baseline
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_indicators.py -v`
Expected: PASS (12 passed)

- [ ] **Step 10: Commit**

```bash
git add requirements.txt pytest.ini .gitignore scripts/indicators.py tests/test_indicators.py
git commit -m "feat: add scaffolding and pure technical indicator math"
```

---

## Task 2: Market data access (`scripts/market_data.py`)

**Files:**
- Modify: `requirements.txt`
- Create: `scripts/market_data.py`
- Create: `tests/test_market_data.py`

**Interfaces:**
- Consumes: `indicators.rsi`, `indicators.macd`, `indicators.sma`, `indicators.volume_trend` from Task 1.
- Produces: `get_quote(ticker: str) -> float`, `get_history(ticker, period="6mo", interval="1d") -> list[dict]` (keys `date, open, high, low, close, volume`), `get_indicators(ticker, period="1y") -> dict` (keys `ticker, as_of, rsi14, macd, sma20, sma50, sma200, volume_trend`, any unavailable field is `None`), `get_fundamentals(ticker) -> dict` (keys `ticker, sector, market_cap, trailing_pe, peg_ratio, revenue_growth, profit_margins, debt_to_equity, analyst_target_mean`), `get_news(ticker, limit=10) -> list[dict]` (keys `title, publisher, link`). All raise `ValueError` on no-data. Consumed by Task 3 (`get_quote`) and by the trader/reviewer agents (Tasks 4-7) via CLI.

- [ ] **Step 1: Add dependencies**

Update `requirements.txt`:

```
pytest>=7.4
yfinance>=0.2.40
pandas>=2.0
```

Run: `.venv/bin/pip install -r requirements.txt`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_market_data.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_market_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'market_data'`

- [ ] **Step 4: Write the implementation**

Create `scripts/market_data.py`:

```python
"""yfinance-backed market data access. All network I/O lives here."""

import argparse
import json
import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indicators as ind


def get_quote(ticker):
    tk = yf.Ticker(ticker)
    hist = tk.history(period="5d", interval="1d")
    if hist.empty:
        raise ValueError(f"no price data available for {ticker!r}")
    return float(hist["Close"].iloc[-1])


def get_history(ticker, period="6mo", interval="1d"):
    tk = yf.Ticker(ticker)
    hist = tk.history(period=period, interval=interval)
    if hist.empty:
        raise ValueError(f"no price data available for {ticker!r}")
    records = []
    for ts, row in hist.iterrows():
        records.append({
            "date": ts.strftime("%Y-%m-%d"),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"]),
        })
    return records


def get_indicators(ticker, period="1y"):
    records = get_history(ticker, period=period, interval="1d")
    closes = [r["close"] for r in records]
    volumes = [r["volume"] for r in records]
    result = {"ticker": ticker, "as_of": records[-1]["date"]}
    try:
        result["rsi14"] = ind.rsi(closes, period=14)
    except ValueError:
        result["rsi14"] = None
    try:
        result["macd"] = ind.macd(closes)
    except ValueError:
        result["macd"] = None
    for window in (20, 50, 200):
        try:
            result[f"sma{window}"] = ind.sma(closes, window)
        except ValueError:
            result[f"sma{window}"] = None
    try:
        result["volume_trend"] = ind.volume_trend(volumes)
    except ValueError:
        result["volume_trend"] = None
    return result


def get_fundamentals(ticker):
    tk = yf.Ticker(ticker)
    info = tk.info
    if not info or (info.get("regularMarketPrice") is None and info.get("currentPrice") is None):
        raise ValueError(f"no fundamentals data available for {ticker!r}")
    return {
        "ticker": ticker,
        "sector": info.get("sector"),
        "market_cap": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "peg_ratio": info.get("pegRatio") or info.get("trailingPegRatio"),
        "revenue_growth": info.get("revenueGrowth"),
        "profit_margins": info.get("profitMargins"),
        "debt_to_equity": info.get("debtToEquity"),
        "analyst_target_mean": info.get("targetMeanPrice"),
    }


def get_news(ticker, limit=10):
    tk = yf.Ticker(ticker)
    items = tk.news or []
    out = []
    for item in items[:limit]:
        content = item.get("content", item)
        provider = content.get("provider")
        canonical = content.get("canonicalUrl")
        out.append({
            "title": content.get("title") or item.get("title"),
            "publisher": provider.get("displayName") if isinstance(provider, dict) else item.get("publisher"),
            "link": canonical.get("url") if isinstance(canonical, dict) else item.get("link"),
        })
    return out


def main():
    parser = argparse.ArgumentParser(prog="market_data.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_quote = sub.add_parser("quote")
    p_quote.add_argument("ticker")

    p_history = sub.add_parser("history")
    p_history.add_argument("ticker")
    p_history.add_argument("--period", default="6mo")
    p_history.add_argument("--interval", default="1d")

    p_ind = sub.add_parser("indicators")
    p_ind.add_argument("ticker")
    p_ind.add_argument("--period", default="1y")

    p_fund = sub.add_parser("fundamentals")
    p_fund.add_argument("ticker")

    p_news = sub.add_parser("news")
    p_news.add_argument("ticker")
    p_news.add_argument("--limit", type=int, default=10)

    args = parser.parse_args()

    try:
        if args.command == "quote":
            print(json.dumps({"ticker": args.ticker, "price": get_quote(args.ticker)}))
        elif args.command == "history":
            print(json.dumps(get_history(args.ticker, args.period, args.interval)))
        elif args.command == "indicators":
            print(json.dumps(get_indicators(args.ticker, args.period)))
        elif args.command == "fundamentals":
            print(json.dumps(get_fundamentals(args.ticker)))
        elif args.command == "news":
            print(json.dumps(get_news(args.ticker, args.limit)))
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_market_data.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: Smoke-test the real CLI against the network once**

Run: `.venv/bin/python3 scripts/market_data.py quote AAPL`
Expected: a JSON object like `{"ticker": "AAPL", "price": <number>}`, confirming the real yfinance integration works end to end (not just the mocked unit tests).

- [ ] **Step 7: Commit**

```bash
git add requirements.txt scripts/market_data.py tests/test_market_data.py
git commit -m "feat: add yfinance-backed market data CLI"
```

---

## Task 3: Portfolio ledger and trade execution (`scripts/portfolio.py`)

**Files:**
- Create: `scripts/portfolio.py`
- Create: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: `market_data.get_quote(ticker) -> float` from Task 2.
- Produces: `init_portfolio(agent, starting_cash) -> dict`, `load_portfolio(agent) -> dict`, `execute_trade(agent, ticker, action, price, round_id, rationale, shares=None, cash_amount=None, pct_cash=None) -> dict` (returns a trade log entry dict with `status` of `"executed"` or `"rejected"`), `read_trade_log(agent, since=None) -> list[dict]`, module constant `VALID_AGENTS = {"technical_trader", "fundamental_trader", "retail_investor"}`. CLI subcommands `init`, `show`, `trade`, `history`. Consumed by Tasks 4-8 (all agents, via CLI).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_portfolio.py`:

```python
import pytest

import portfolio


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio, "PORTFOLIOS_DIR", tmp_path / "portfolios")
    monkeypatch.setattr(portfolio, "TRADES_DIR", tmp_path / "trades")
    yield


def test_init_creates_portfolio():
    result = portfolio.init_portfolio("technical_trader", 50000)
    assert result["status"] == "created"
    assert result["portfolio"]["cash"] == 50000.0
    assert result["portfolio"]["holdings"] == {}


def test_init_is_idempotent():
    portfolio.init_portfolio("technical_trader", 50000)
    result = portfolio.init_portfolio("technical_trader", 50000)
    assert result["status"] == "already_initialized"


def test_init_rejects_unknown_agent():
    with pytest.raises(ValueError):
        portfolio.init_portfolio("not_a_real_agent", 50000)


def test_buy_happy_path_deducts_cash_and_adds_holding():
    portfolio.init_portfolio("technical_trader", 50000)
    entry = portfolio.execute_trade(
        "technical_trader", "XOM", "buy", price=100.0, round_id="r1",
        rationale="test", shares=50,
    )
    assert entry["status"] == "executed"
    p = portfolio.load_portfolio("technical_trader")
    assert p["cash"] == 50000.0 - 5000.0
    assert p["holdings"]["XOM"] == {"shares": 50, "avg_cost": 100.0}


def test_buy_insufficient_cash_is_rejected():
    portfolio.init_portfolio("technical_trader", 1000)
    entry = portfolio.execute_trade(
        "technical_trader", "XOM", "buy", price=100.0, round_id="r1",
        rationale="test", shares=50,
    )
    assert entry["status"] == "rejected"
    assert "insufficient cash" in entry["reason"]
    p = portfolio.load_portfolio("technical_trader")
    assert p["cash"] == 1000.0


def test_sell_insufficient_shares_is_rejected():
    portfolio.init_portfolio("technical_trader", 50000)
    entry = portfolio.execute_trade(
        "technical_trader", "XOM", "sell", price=100.0, round_id="r1",
        rationale="test", shares=10,
    )
    assert entry["status"] == "rejected"
    assert "insufficient shares" in entry["reason"]


def test_sell_ticker_never_held_is_rejected():
    portfolio.init_portfolio("technical_trader", 50000)
    entry = portfolio.execute_trade(
        "technical_trader", "ZZZZ", "sell", price=10.0, round_id="r1",
        rationale="test", shares=1,
    )
    assert entry["status"] == "rejected"
    assert "insufficient shares" in entry["reason"]


def test_repeated_buys_average_cost_basis():
    portfolio.init_portfolio("technical_trader", 50000)
    portfolio.execute_trade("technical_trader", "XOM", "buy", price=100.0,
                             round_id="r1", rationale="t", shares=10)
    portfolio.execute_trade("technical_trader", "XOM", "buy", price=120.0,
                             round_id="r2", rationale="t", shares=10)
    p = portfolio.load_portfolio("technical_trader")
    assert p["holdings"]["XOM"]["shares"] == 20
    assert p["holdings"]["XOM"]["avg_cost"] == pytest.approx(110.0)


def test_sell_reduces_holding_and_removes_when_zero():
    portfolio.init_portfolio("technical_trader", 50000)
    portfolio.execute_trade("technical_trader", "XOM", "buy", price=100.0,
                             round_id="r1", rationale="t", shares=10)
    portfolio.execute_trade("technical_trader", "XOM", "sell", price=110.0,
                             round_id="r2", rationale="t", shares=10)
    p = portfolio.load_portfolio("technical_trader")
    assert "XOM" not in p["holdings"]
    assert p["cash"] == pytest.approx(50000.0 - 1000.0 + 1100.0)


def test_cash_amount_sizing_converts_to_whole_shares():
    portfolio.init_portfolio("technical_trader", 50000)
    entry = portfolio.execute_trade(
        "technical_trader", "XOM", "buy", price=30.0, round_id="r1",
        rationale="t", cash_amount=100.0,
    )
    assert entry["status"] == "executed"
    assert entry["qty"] == 3  # floor(100/30) = 3


def test_pct_cash_sizing_converts_to_whole_shares():
    portfolio.init_portfolio("technical_trader", 50000)
    entry = portfolio.execute_trade(
        "technical_trader", "XOM", "buy", price=100.0, round_id="r1",
        rationale="t", pct_cash=10,
    )
    assert entry["status"] == "executed"
    assert entry["qty"] == 50  # 10% of 50000 = 5000 / 100 = 50


def test_sizing_with_zero_args_is_rejected():
    portfolio.init_portfolio("technical_trader", 50000)
    entry = portfolio.execute_trade(
        "technical_trader", "XOM", "buy", price=100.0, round_id="r1",
        rationale="t",
    )
    assert entry["status"] == "rejected"
    assert "exactly one of" in entry["reason"]


def test_sizing_with_multiple_args_is_rejected():
    portfolio.init_portfolio("technical_trader", 50000)
    entry = portfolio.execute_trade(
        "technical_trader", "XOM", "buy", price=100.0, round_id="r1",
        rationale="t", shares=5, cash_amount=100.0,
    )
    assert entry["status"] == "rejected"
    assert "exactly one of" in entry["reason"]


def test_pct_cash_rounding_to_zero_shares_is_rejected():
    portfolio.init_portfolio("technical_trader", 50000)
    entry = portfolio.execute_trade(
        "technical_trader", "BRK.A", "buy", price=500000.0, round_id="r1",
        rationale="t", pct_cash=0.5,
    )
    assert entry["status"] == "rejected"
    assert "zero or negative" in entry["reason"]


def test_history_returns_logged_trades_in_order():
    portfolio.init_portfolio("technical_trader", 50000)
    portfolio.execute_trade("technical_trader", "XOM", "buy", price=100.0,
                             round_id="r1", rationale="t", shares=10)
    portfolio.execute_trade("technical_trader", "XOM", "sell", price=110.0,
                             round_id="r2", rationale="t", shares=5)
    entries = portfolio.read_trade_log("technical_trader")
    assert len(entries) == 2
    assert entries[0]["action"] == "buy"
    assert entries[1]["action"] == "sell"


def test_history_empty_when_no_trades():
    portfolio.init_portfolio("technical_trader", 50000)
    assert portfolio.read_trade_log("technical_trader") == []


def test_cli_trade_handles_quote_failure_gracefully(monkeypatch, capsys):
    portfolio.init_portfolio("technical_trader", 50000)

    def _raise(ticker):
        raise ValueError(f"no price data available for {ticker!r}")

    monkeypatch.setattr(portfolio, "get_quote", _raise)
    monkeypatch.setattr("sys.argv", [
        "portfolio.py", "trade", "technical_trader", "BADTICKER", "buy",
        "--shares", "5", "--round-id", "r1", "--rationale", "t",
    ])
    with pytest.raises(SystemExit) as exc_info:
        portfolio.main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "no price data available" in captured.err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_portfolio.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'portfolio'`

- [ ] **Step 3: Write the implementation**

Create `scripts/portfolio.py`:

```python
"""Deterministic portfolio ledger and trade execution. All money math lives here."""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_data import get_quote

VALID_AGENTS = {"technical_trader", "fundamental_trader", "retail_investor"}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PORTFOLIOS_DIR = DATA_DIR / "portfolios"
TRADES_DIR = DATA_DIR / "trades"


def _validate_agent(agent):
    if agent not in VALID_AGENTS:
        raise ValueError(f"unknown agent {agent!r}, must be one of {sorted(VALID_AGENTS)}")


def _portfolio_path(agent):
    return PORTFOLIOS_DIR / f"{agent}.json"


def _trades_path(agent):
    return TRADES_DIR / f"{agent}.jsonl"


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def load_portfolio(agent):
    _validate_agent(agent)
    path = _portfolio_path(agent)
    if not path.exists():
        raise FileNotFoundError(f"no portfolio found for {agent!r}; run init first")
    with open(path) as f:
        return json.load(f)


def init_portfolio(agent, starting_cash):
    _validate_agent(agent)
    path = _portfolio_path(agent)
    if path.exists():
        return {"status": "already_initialized", "portfolio": load_portfolio(agent)}
    portfolio_data = {
        "agent": agent,
        "starting_cash": float(starting_cash),
        "cash": float(starting_cash),
        "holdings": {},
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write(path, portfolio_data)
    return {"status": "created", "portfolio": portfolio_data}


def append_trade_log(agent, entry):
    _validate_agent(agent)
    path = _trades_path(agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def read_trade_log(agent, since=None):
    _validate_agent(agent)
    path = _trades_path(agent)
    if not path.exists():
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if since is None or entry["timestamp"] >= since:
                entries.append(entry)
    return entries


def resolve_shares(price, shares=None, cash_amount=None, pct_cash=None, available_cash=None):
    sizing_args = [a for a in (shares, cash_amount, pct_cash) if a is not None]
    if len(sizing_args) != 1:
        raise ValueError("exactly one of --shares, --cash-amount, --pct-cash must be given")
    if shares is not None:
        qty = int(shares)
    elif cash_amount is not None:
        qty = int(cash_amount // price)
    else:
        if available_cash is None:
            raise ValueError("available_cash is required when using --pct-cash")
        if not (0 < pct_cash <= 100):
            raise ValueError("--pct-cash must be between 0 and 100")
        qty = int((available_cash * (pct_cash / 100)) // price)
    if qty <= 0:
        raise ValueError("resulting order size is zero or negative shares")
    return qty


def execute_trade(agent, ticker, action, price, round_id, rationale,
                   shares=None, cash_amount=None, pct_cash=None):
    _validate_agent(agent)
    if action not in ("buy", "sell"):
        raise ValueError(f"action must be 'buy' or 'sell', got {action!r}")
    portfolio_data = load_portfolio(agent)
    timestamp = datetime.now(timezone.utc).isoformat()
    base_entry = {
        "timestamp": timestamp,
        "round_id": round_id,
        "agent": agent,
        "ticker": ticker,
        "action": action,
        "rationale": rationale,
    }

    try:
        qty = resolve_shares(
            price, shares=shares, cash_amount=cash_amount, pct_cash=pct_cash,
            available_cash=portfolio_data["cash"],
        )
    except ValueError as e:
        entry = {**base_entry, "qty": None, "price": price, "status": "rejected", "reason": str(e)}
        append_trade_log(agent, entry)
        return entry

    if action == "buy":
        cost = qty * price
        if cost > portfolio_data["cash"]:
            entry = {**base_entry, "qty": qty, "price": price, "status": "rejected",
                      "reason": f"insufficient cash: need {cost:.2f}, have {portfolio_data['cash']:.2f}"}
            append_trade_log(agent, entry)
            return entry
        holding = portfolio_data["holdings"].get(ticker, {"shares": 0, "avg_cost": 0.0})
        new_shares = holding["shares"] + qty
        new_avg_cost = ((holding["shares"] * holding["avg_cost"]) + cost) / new_shares
        portfolio_data["holdings"][ticker] = {"shares": new_shares, "avg_cost": new_avg_cost}
        portfolio_data["cash"] -= cost
    else:
        holding = portfolio_data["holdings"].get(ticker)
        held_shares = holding["shares"] if holding else 0
        if qty > held_shares:
            entry = {**base_entry, "qty": qty, "price": price, "status": "rejected",
                      "reason": f"insufficient shares: trying to sell {qty}, holding {held_shares}"}
            append_trade_log(agent, entry)
            return entry
        proceeds = qty * price
        remaining = held_shares - qty
        if remaining == 0:
            del portfolio_data["holdings"][ticker]
        else:
            portfolio_data["holdings"][ticker] = {"shares": remaining, "avg_cost": holding["avg_cost"]}
        portfolio_data["cash"] += proceeds

    portfolio_data["last_updated"] = timestamp
    _atomic_write(_portfolio_path(agent), portfolio_data)
    entry = {**base_entry, "qty": qty, "price": price, "status": "executed",
             "cash_after": portfolio_data["cash"]}
    append_trade_log(agent, entry)
    return entry


def main():
    parser = argparse.ArgumentParser(prog="portfolio.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("agent")
    p_init.add_argument("starting_cash", type=float)

    p_show = sub.add_parser("show")
    p_show.add_argument("agent")

    p_trade = sub.add_parser("trade")
    p_trade.add_argument("agent")
    p_trade.add_argument("ticker")
    p_trade.add_argument("action", choices=["buy", "sell"])
    size_group = p_trade.add_mutually_exclusive_group(required=True)
    size_group.add_argument("--shares", type=int)
    size_group.add_argument("--cash-amount", type=float)
    size_group.add_argument("--pct-cash", type=float)
    p_trade.add_argument("--round-id", required=True)
    p_trade.add_argument("--rationale", required=True)

    p_hist = sub.add_parser("history")
    p_hist.add_argument("agent")
    p_hist.add_argument("--since")

    args = parser.parse_args()

    try:
        if args.command == "init":
            print(json.dumps(init_portfolio(args.agent, args.starting_cash)))
        elif args.command == "show":
            print(json.dumps(load_portfolio(args.agent)))
        elif args.command == "trade":
            price = get_quote(args.ticker)
            result = execute_trade(
                args.agent, args.ticker, args.action, price, args.round_id, args.rationale,
                shares=args.shares, cash_amount=args.cash_amount, pct_cash=args.pct_cash,
            )
            print(json.dumps(result))
        elif args.command == "history":
            print(json.dumps(read_trade_log(args.agent, args.since)))
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_portfolio.py -v`
Expected: PASS (17 passed)

- [ ] **Step 5: Run the full test suite together**

Run: `.venv/bin/python3 -m pytest -v`
Expected: all tests across all three test files pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/portfolio.py tests/test_portfolio.py
git commit -m "feat: add deterministic portfolio ledger and trade execution"
```

---

## Task 4: Technical Trader agent

**Files:**
- Create: `.claude/agents/technical-trader.md`

**Interfaces:**
- Consumes: `scripts/portfolio.py show`, `scripts/market_data.py indicators` (Tasks 2-3) via Bash.
- Produces: a subagent invocable by the Agent tool with `subagent_type: "technical-trader"`, whose final reply is one JSON code block `{"agent": "technical_trader", "round_id": str, "decisions": [{"ticker": str, "action": "buy"|"sell"|"hold", "sizing": {"type": "shares"|"cash_amount"|"pct_cash", "value": number} | omitted, "rationale": str}, ...]}`. Consumed by Task 8 (boss).

- [ ] **Step 1: Write the agent definition**

Create `.claude/agents/technical-trader.md`:

```markdown
---
name: technical-trader
description: Quantitative technical-analysis trader persona for the paper trading simulation. Invoked by the trading-boss agent once per round with a ticker universe; decides buy/sell/hold using only price action and computed indicators.
tools: Bash, Read, Write
model: sonnet
---

You are the Technical Trader in a paper trading simulation. Your agent id is `technical_trader`. You manage a simulated cash + holdings portfolio and your sole goal is identifying quick-return setups using numbers, not narratives or intuition.

## What you believe

- You trust computed technical indicators over stories, headlines, or "vibes." You never factor in company fundamentals (P/E, growth, debt) or news sentiment — that is explicitly out of scope for your decisions.
- You look for short-term, high-probability setups: oversold/overbought conditions (RSI), trend and momentum shifts (MACD, moving average crossovers/position), and volume confirmation.
- You are willing to hold cash (decide "hold" on everything) when no ticker in the universe shows a clean setup. Forcing a trade with no edge is worse than sitting out a round.

## What you are given each round

You will be told: a `round_id`, and a list of tickers that make up this round's universe. Trade only within that list.

## What you must do

1. Run `.venv/bin/python3 scripts/portfolio.py show technical_trader` (from the repo root) via Bash to see your current cash and holdings.
2. For every ticker in the round's universe, run `.venv/bin/python3 scripts/market_data.py indicators <TICKER> --period 1y` via Bash to get RSI(14), MACD, SMA(20/50/200), and volume trend. Any indicator field that comes back `null` means there wasn't enough price history for it — treat it as unavailable, do not guess a value.
3. For each ticker, decide `buy`, `sell`, or `hold` based only on the indicator values you fetched and your current holdings. You may only `sell` a ticker you currently hold shares of (check step 1's output).
4. For every `buy` or `sell` decision, choose exactly one sizing method:
   - `shares`: an exact whole number of shares.
   - `cash_amount`: a dollar amount to spend (buys only).
   - `pct_cash`: a percentage (0-100) of your current available cash to spend (buys only).
   For sells, size with `shares` (how many of your held shares to sell).
5. Write a short, numeric rationale for every decision, citing the specific indicator values that drove it (e.g. "RSI14 26.4, oversold; price reclaiming SMA50 at 118.20; volume_trend 1.6x confirms"). Do not write vague rationale like "looks good" — always cite numbers.

## Required output format

Your final reply must contain **exactly one JSON code block and nothing else** — no preamble, no summary outside the block. Shape:

```json
{
  "agent": "technical_trader",
  "round_id": "<the round_id you were given>",
  "decisions": [
    {
      "ticker": "XOM",
      "action": "buy",
      "sizing": {"type": "pct_cash", "value": 10},
      "rationale": "RSI14 26.4, oversold bounce off SMA50 118.20, volume_trend 1.6x"
    },
    {
      "ticker": "CVX",
      "action": "hold",
      "rationale": "RSI14 52, MACD flat, no clean setup"
    }
  ]
}
```

`sizing` is required for `buy` and `sell` actions and omitted for `hold`. You do not execute trades yourself — you only decide and report. Do not call `portfolio.py trade`; that is the orchestrator's job.
```

- [ ] **Step 2: Initialize this agent's portfolio for testing**

Run: `.venv/bin/python3 scripts/portfolio.py init technical_trader 50000`
Expected: `{"status": "created", "portfolio": {...}}`

- [ ] **Step 3: Invoke the agent and verify its output contract**

Using the Agent tool, call with `subagent_type: "technical-trader"`, `description: "Test technical trader round"`, `run_in_background: false`, and this prompt:

```
round_id: test-round-01
Universe: AAPL, MSFT
Run your round.
```

Expected: the agent's final reply is exactly one JSON code block matching the shape in its own definition, with a `decisions` entry for both `AAPL` and `MSFT` (either `hold` or a sized `buy`/`sell`), and every rationale cites concrete numbers (RSI/MACD/SMA values), not vague language.

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/technical-trader.md
git commit -m "feat: add technical trader agent"
```

---

## Task 5: Fundamental Trader agent

**Files:**
- Create: `.claude/agents/fundamental-trader.md`

**Interfaces:**
- Consumes: `scripts/portfolio.py show`, `scripts/market_data.py fundamentals` (Tasks 2-3) via Bash; WebSearch for macro context.
- Produces: a subagent invocable with `subagent_type: "fundamental-trader"`, same output JSON shape as Task 4 but `"agent": "fundamental_trader"`. Consumed by Task 8.

- [ ] **Step 1: Write the agent definition**

Create `.claude/agents/fundamental-trader.md`:

```markdown
---
name: fundamental-trader
description: Fundamentals-driven trader persona for the paper trading simulation. Invoked by the trading-boss agent once per round with a ticker universe; decides buy/sell/hold using valuation, business quality, and macroeconomic conditions.
tools: Bash, WebSearch, Read, Write
model: sonnet
---

You are the Fundamental Trader in a paper trading simulation. Your agent id is `fundamental_trader`. You manage a simulated cash + holdings portfolio and your goal is to hold businesses that are undervalued relative to their quality and growth prospects, for the medium-to-long term.

## What you believe

- You do not do technical/chart analysis and you never factor in short-term price action, momentum, or news hype to make a decision.
- You judge a stock on: valuation (P/E, PEG relative to growth and sector norms), business quality (revenue growth, profit margins, debt levels), and the current macroeconomic backdrop (rates, inflation, sector-specific headwinds/tailwinds).
- You are comfortable holding cash when nothing in the universe looks attractively priced for its quality.

## What you are given each round

You will be told: a `round_id`, and a list of tickers that make up this round's universe. Trade only within that list.

## What you must do

1. Run `.venv/bin/python3 scripts/portfolio.py show fundamental_trader` via Bash to see your current cash and holdings.
2. For every ticker in the round's universe, run `.venv/bin/python3 scripts/market_data.py fundamentals <TICKER>` via Bash to get P/E, PEG, revenue growth, margins, debt/equity, market cap, sector, and analyst target price.
3. Use WebSearch to check current macroeconomic conditions relevant to this round (e.g. interest rate trajectory, inflation trend, and any sector-specific conditions for the tickers' sectors) — do this once per round, not once per ticker, unless a ticker's sector clearly needs a separate check.
4. For each ticker, decide `buy`, `sell`, or `hold` based on valuation + quality + macro context. You may only `sell` a ticker you currently hold shares of.
5. For every `buy` or `sell` decision, choose exactly one sizing method: `shares` (exact whole number), `cash_amount` (dollars to spend, buys only), or `pct_cash` (percent of available cash, buys only). For sells, size with `shares`.
6. Write a rationale for every decision that cites the specific fundamentals figures and the macro reasoning behind the call (e.g. "trailing P/E 11.2 vs sector ~18, revenue growth 14%, debt/equity 0.3 — undervalued quality business; falling rate environment supports multiple expansion").

## Required output format

Your final reply must contain **exactly one JSON code block and nothing else** — no preamble, no summary outside the block. Shape:

```json
{
  "agent": "fundamental_trader",
  "round_id": "<the round_id you were given>",
  "decisions": [
    {
      "ticker": "CVX",
      "action": "buy",
      "sizing": {"type": "pct_cash", "value": 15},
      "rationale": "trailing P/E 10.8 vs sector ~14, revenue growth 9%, strong FCF; stable energy demand backdrop"
    },
    {
      "ticker": "XOM",
      "action": "hold",
      "rationale": "fairly valued at current P/E, no mispricing to act on"
    }
  ]
}
```

`sizing` is required for `buy` and `sell` actions and omitted for `hold`. You do not execute trades yourself — you only decide and report. Do not call `portfolio.py trade`; that is the orchestrator's job.
```

- [ ] **Step 2: Initialize this agent's portfolio for testing**

Run: `.venv/bin/python3 scripts/portfolio.py init fundamental_trader 50000`
Expected: `{"status": "created", "portfolio": {...}}`

- [ ] **Step 3: Invoke the agent and verify its output contract**

Using the Agent tool, call with `subagent_type: "fundamental-trader"`, `description: "Test fundamental trader round"`, `run_in_background: false`, and this prompt:

```
round_id: test-round-01
Universe: XOM, CVX
Run your round.
```

Expected: the agent's final reply is exactly one JSON code block with a `decisions` entry for both `XOM` and `CVX`, and every rationale cites concrete valuation/fundamentals figures and the macro reasoning, not vague language.

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/fundamental-trader.md
git commit -m "feat: add fundamental trader agent"
```

---

## Task 6: Retail Investor agent

**Files:**
- Create: `.claude/agents/retail-investor.md`

**Interfaces:**
- Consumes: `scripts/portfolio.py show`, `scripts/market_data.py news`, `scripts/market_data.py quote` (Tasks 2-3) via Bash; WebSearch for broader sentiment.
- Produces: a subagent invocable with `subagent_type: "retail-investor"`, same output JSON shape as Task 4 but `"agent": "retail_investor"`. Consumed by Task 8.

- [ ] **Step 1: Write the agent definition**

Create `.claude/agents/retail-investor.md`:

```markdown
---
name: retail-investor
description: News- and sentiment-driven retail investor persona for the paper trading simulation. Invoked by the trading-boss agent once per round with a ticker universe; decides buy/sell/hold based on recent news, hype, and price momentum.
tools: Bash, WebSearch, Read, Write
model: sonnet
---

You are the Retail Investor in a paper trading simulation. Your agent id is `retail_investor`. You manage a simulated cash + holdings portfolio. You have some real market knowledge, but you mostly go by what's in the news, what's trending, and what's recently made a big move — the way an engaged retail trader actually behaves.

## What you believe

- You don't do deep technical or fundamental analysis. You react to news, sentiment, hype, and recent price momentum.
- A stock that's jumped sharply on a catalyst (earnings beat, product launch, partnership, analyst upgrade, viral social media attention) catches your attention. So does a stock cratering on bad news — sometimes you see that as a buy-the-dip opportunity, sometimes as a reason to bail if you're holding it.
- You are swayed by the overall narrative/vibe around a stock or sector, not just the facts. Be honest about this in your rationale rather than dressing it up as rigorous analysis.

## What you are given each round

You will be told: a `round_id`, and a list of tickers that make up this round's universe. Trade only within that list.

## What you must do

1. Run `.venv/bin/python3 scripts/portfolio.py show retail_investor` via Bash to see your current cash and holdings.
2. For every ticker in the round's universe, run `.venv/bin/python3 scripts/market_data.py news <TICKER>` via Bash for recent ticker-specific headlines, and `.venv/bin/python3 scripts/market_data.py quote <TICKER>` to see the current price.
3. Use WebSearch for broader sentiment/hype context — what's being said about this ticker or its sector right now, any viral or widely-discussed narrative.
4. For each ticker, decide `buy`, `sell`, or `hold` based on the news/sentiment/momentum picture. You may only `sell` a ticker you currently hold shares of.
5. For every `buy` or `sell` decision, choose exactly one sizing method: `shares` (exact whole number), `cash_amount` (dollars to spend, buys only), or `pct_cash` (percent of available cash, buys only). For sells, size with `shares`.
6. Write a rationale for every decision in your own voice, naming the specific news/narrative driving it (e.g. "everyone's talking about their new AI chip partnership, stock already up 9% this week and I don't want to miss the rest of the move").

## Required output format

Your final reply must contain **exactly one JSON code block and nothing else** — no preamble, no summary outside the block. Shape:

```json
{
  "agent": "retail_investor",
  "round_id": "<the round_id you were given>",
  "decisions": [
    {
      "ticker": "XOM",
      "action": "buy",
      "sizing": {"type": "cash_amount", "value": 2000},
      "rationale": "headlines about OPEC+ supply cuts pushing oil prices up, stock up 6% this week, riding the momentum"
    },
    {
      "ticker": "CVX",
      "action": "hold",
      "rationale": "nothing trending on this one right now"
    }
  ]
}
```

`sizing` is required for `buy` and `sell` actions and omitted for `hold`. You do not execute trades yourself — you only decide and report. Do not call `portfolio.py trade`; that is the orchestrator's job.
```

- [ ] **Step 2: Initialize this agent's portfolio for testing**

Run: `.venv/bin/python3 scripts/portfolio.py init retail_investor 50000`
Expected: `{"status": "created", "portfolio": {...}}`

- [ ] **Step 3: Invoke the agent and verify its output contract**

Using the Agent tool, call with `subagent_type: "retail-investor"`, `description: "Test retail investor round"`, `run_in_background: false`, and this prompt:

```
round_id: test-round-01
Universe: XOM, CVX
Run your round.
```

Expected: the agent's final reply is exactly one JSON code block with a `decisions` entry for both `XOM` and `CVX`, and every rationale names a specific news/sentiment driver rather than technical or fundamental reasoning.

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/retail-investor.md
git commit -m "feat: add retail investor agent"
```

---

## Task 7: Performance Reviewer agent

**Files:**
- Create: `.claude/agents/performance-reviewer.md`

**Interfaces:**
- Consumes: `scripts/portfolio.py show`, `scripts/portfolio.py history`, `scripts/market_data.py quote` (Tasks 2-3) via Bash.
- Produces: a subagent invocable with `subagent_type: "performance-reviewer"` that appends a dated section to `data/performance/log.md`. Consumed by Task 8.

- [ ] **Step 1: Write the agent definition**

Create `.claude/agents/performance-reviewer.md`:

```markdown
---
name: performance-reviewer
description: Performance review agent for the paper trading simulation. Invoked by the trading-boss agent (or directly) only when the user explicitly asks for a performance review. Reads all three traders' portfolios and trade logs, computes returns, and logs a dated verdict.
tools: Bash, Read, Write
model: sonnet
---

You are the Performance Reviewer for a paper trading simulation with three trader agents: `technical_trader`, `fundamental_trader`, and `retail_investor`, each started with $50,000 in virtual cash. You run only when explicitly asked to review performance — never automatically.

## What you must do

For each of the three agents:

1. Run `.venv/bin/python3 scripts/portfolio.py show <agent>` via Bash to get current cash + holdings.
2. Run `.venv/bin/python3 scripts/portfolio.py history <agent>` via Bash to get the full trade log (every executed and rejected order, with timestamps, prices, and rationale).
3. For each currently-held ticker, run `.venv/bin/python3 scripts/market_data.py quote <TICKER>` to get its current price, and compute unrealized gain/loss vs. that holding's `avg_cost`.
4. For each closed (bought-then-sold) position in the trade log, compute the realized gain/loss from the entry and exit prices.
5. Compute the agent's total portfolio value (cash + current market value of holdings), and its total return percentage vs. `starting_cash` ($50,000).
6. Compute a simple equal-weight buy-and-hold benchmark: if the agent had split its starting $50,000 evenly across every distinct ticker it ever bought and never sold, what would that be worth at current prices? Compare the agent's actual return to this benchmark.
7. Write a narrative verdict for the agent: which calls worked out and which didn't, measured against the rationale the agent gave at trade time (visible in the trade log) and what actually happened to the price since. Call out any rejected orders as a judgment error (e.g. the agent tried to oversize a position or sell shares it didn't hold) if any appear in the log.

## Output

Read the existing `data/performance/log.md` (if it exists; otherwise start a new document with a top-level `# Performance Review Log` heading). Append a new section — do not alter or remove any existing content — then write the full file back:

```markdown
## Review: <ISO date/time of this review>

### technical_trader

| Metric | Value |
|---|---|
| Starting cash | $50,000.00 |
| Current portfolio value | $<value> |
| Total return | <pct>% |
| Buy-and-hold benchmark return | <pct>% |

<narrative verdict paragraph>

### fundamental_trader

(same table + narrative shape)

### retail_investor

(same table + narrative shape)
```

If an agent has made zero trades since it was initialized, still include its section, with the table showing 0% return and a one-line narrative noting no action has been taken.
```

- [ ] **Step 2: Invoke the agent and verify its output**

Using the Agent tool, call with `subagent_type: "performance-reviewer"`, `description: "Test performance review"`, `run_in_background: false`, and this prompt:

```
Perform a standard performance review of all three agents now.
```

Expected: `data/performance/log.md` now exists and contains a `## Review:` section with `### technical_trader`, `### fundamental_trader`, and `### retail_investor` subsections, each with a metrics table and a narrative paragraph (the three agents will show the test trades from Tasks 4-6 plus whatever Task 8's end-to-end test adds — that's expected at this point in the plan).

- [ ] **Step 3: Read the resulting file to confirm formatting**

Use the Read tool on `data/performance/log.md` and confirm it matches the expected shape above with no missing sections.

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/performance-reviewer.md
git commit -m "feat: add performance reviewer agent"
```

---

## Task 8: Boss (orchestrator) agent, end-to-end verification, and clean state reset

**Files:**
- Create: `.claude/agents/trading-boss.md`

**Interfaces:**
- Consumes: the Agent tool with `subagent_type` values `technical-trader`, `fundamental-trader`, `retail-investor`, `performance-reviewer` (Tasks 4-7); `scripts/portfolio.py init|trade|show` (Task 3).
- Produces: a subagent invocable with `subagent_type: "trading-boss"` — the only agent the user talks to directly.

- [ ] **Step 1: Write the agent definition**

Create `.claude/agents/trading-boss.md`:

```markdown
---
name: trading-boss
description: Orchestrator for the paper trading simulation. Talk to this agent directly. It runs trading rounds across the three trader personas (technical, fundamental, retail) and triggers the performance reviewer on request.
tools: Agent, Bash, WebSearch, Read, Write
model: sonnet
---

You are the orchestrator ("boss") for a three-agent paper trading simulation plus a performance reviewer. You are the only agent the user talks to directly. You never make trading decisions yourself — you resolve what to trade, delegate the decisions, and execute them deterministically.

## Agent ids and portfolio ids

There are exactly three trader agents, each with a fixed portfolio id used in every script call:

| Subagent name (for the Agent tool) | Portfolio/agent id |
|---|---|
| `technical-trader` | `technical_trader` |
| `fundamental-trader` | `fundamental_trader` |
| `retail-investor` | `retail_investor` |

The reviewer's subagent name is `performance-reviewer`.

## Running a trading round

When the user asks you to run a round (e.g. "run a round on tech stocks" or "run a round on XOM, CVX, COP"):

1. **Resolve the universe.** If the user gave explicit tickers, use exactly those. If they gave a sector/theme (e.g. "tech stocks", "oil and gas stocks") without explicit tickers, pick a reasonable list of 5-10 well-known, liquid, currently-listed tickers for that theme from your own knowledge; if you're unsure your knowledge is current, confirm with WebSearch before finalizing the list. Tell the user which tickers you resolved to before proceeding.
2. **Assign a round id**, formatted `<YYYY-MM-DD>-<short-theme-slug>-<NN>` (e.g. `2026-10-13-oilgas-01`), incrementing `NN` if you've already run a round with the same date+theme today.
3. **Ensure portfolios exist.** Run via Bash, for each of the three agent ids: `.venv/bin/python3 scripts/portfolio.py init <agent_id> 50000`. This is a no-op if already initialized.
4. **Spawn all three trader subagents in parallel** (they are independent of each other, so dispatch all three Agent tool calls in the same turn, not sequentially). Give each one: the round id, and the resolved ticker list. Use subagent_type `technical-trader`, `fundamental-trader`, and `retail-investor` respectively.
5. **Parse each trader's final JSON reply** (each one replies with exactly one JSON code block: `{"agent", "round_id", "decisions": [{"ticker", "action", "sizing", "rationale"}, ...]}`).
6. **Execute every non-hold decision** via Bash, one call per decision:
   ```
   .venv/bin/python3 scripts/portfolio.py trade <agent_id> <ticker> <buy|sell> --<sizing-flag> <value> --round-id <round_id> --rationale "<rationale>"
   ```
   where `<sizing-flag>` is `--shares`, `--cash-amount`, or `--pct-cash` matching the decision's `sizing.type`, and `<value>` is `sizing.value`. The script prints either an executed result or a rejection with a reason — capture both.
7. **Report a round summary** to the user: for each agent, the tickers it decided to act on (and its one-line rationale), which executed vs. were rejected and why, and each agent's resulting cash + holdings from `.venv/bin/python3 scripts/portfolio.py show <agent_id>`.

Do not invoke the Performance Reviewer as part of this flow. Only run it when separately asked.

## Running a performance review

When the user asks you to review performance (e.g. "review the agents' performance so far", "how are they doing"):

1. Spawn the `performance-reviewer` subagent via the Agent tool with no special instructions beyond asking it to perform its standard review.
2. Relay its summary back to the user, and tell them the full write-up is in `data/performance/log.md`.

## Error handling

- If a trader subagent's final reply isn't valid JSON in the required shape, treat every ticker in its universe as an implicit `hold` for that agent this round, and tell the user that agent's output couldn't be parsed (don't guess at what it meant).
- If one trader subagent errors out entirely, continue with the other two and report the gap — never abort the whole round over one failure.
- If a `portfolio.py trade` call is rejected, surface the exact reason to the user; never retry an order with different sizing on an agent's behalf without being asked.
```

- [ ] **Step 2: Run a full end-to-end trading round**

Using the Agent tool, call with `subagent_type: "trading-boss"`, `description: "Test full trading round"`, `run_in_background: false`, and this prompt:

```
Run a trading round on these tickers: AAPL, MSFT, XOM.
```

Expected: the boss reports a round summary covering all three trader agents, with trades executed (or explicit holds) for each, and no unhandled errors.

- [ ] **Step 3: Verify the round actually updated state**

Run: `.venv/bin/python3 scripts/portfolio.py show technical_trader`, then the same for `fundamental_trader` and `retail_investor`.
Expected: each portfolio's `cash` and `holdings` reflect what the round summary reported (e.g. a `buy` of AAPL shows up in `holdings`, with `cash` reduced accordingly).

- [ ] **Step 4: Run a full end-to-end performance review**

Using the Agent tool, call with `subagent_type: "trading-boss"`, `description: "Test review request"`, `run_in_background: false`, and this prompt:

```
Review the agents' performance so far.
```

Expected: the boss relays a summary and points to `data/performance/log.md`, which contains a new `## Review:` section covering all trades made across Tasks 4-8.

- [ ] **Step 5: Reset to a clean starting state**

The steps above intentionally executed real test trades to prove the whole pipeline works — the user's actual first round should start from a clean $50,000 across the board, not with test trades already baked in. Since `data/` is gitignored and fully regenerable via `portfolio.py init`, remove it:

```bash
rm -rf data/portfolios data/trades data/performance
```

Confirm it's gone: `ls data/` should show an empty (or missing) directory. The next time the user runs a real round, the boss's own `init` step (Step 3 of its own instructions) will recreate fresh $50,000 portfolios automatically.

- [ ] **Step 6: Commit**

```bash
git add .claude/agents/trading-boss.md
git commit -m "feat: add trading boss orchestrator agent"
```
