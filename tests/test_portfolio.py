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
