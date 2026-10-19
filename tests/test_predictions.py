import pytest

import predictions


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(predictions, "PREDICTIONS_DIR", tmp_path / "predictions")
    yield


def test_start_round_creates_empty_predictions():
    result = predictions.start_round("2026-10-20", ["NVDA", "AVGO"])
    assert result["status"] == "created"
    assert result["round"]["date"] == "2026-10-20"
    assert result["round"]["tickers"] == ["NVDA", "AVGO"]
    assert result["round"]["predictions"] == []


def test_start_round_rejects_empty_tickers():
    with pytest.raises(ValueError):
        predictions.start_round("2026-10-20", [])


def test_start_round_is_idempotent():
    predictions.start_round("2026-10-20", ["NVDA"])
    result = predictions.start_round("2026-10-20", ["NVDA"])
    assert result["status"] == "already_started"
    assert result["round"]["tickers"] == ["NVDA"]


def test_show_round_raises_for_unknown_date():
    with pytest.raises(FileNotFoundError):
        predictions.show_round("2026-10-20")


def test_record_prediction_adds_entry():
    predictions.start_round("2026-10-20", ["NVDA", "AVGO"])
    result = predictions.record_prediction(
        "2026-10-20", "technical_trader", "NVDA", 221.50, "RSI14 32.9, buying the pullback within the uptrend",
    )
    assert len(result["predictions"]) == 1
    entry = result["predictions"][0]
    assert entry["agent"] == "technical_trader"
    assert entry["ticker"] == "NVDA"
    assert entry["predicted_close"] == 221.50
    assert entry["rationale"] == "RSI14 32.9, buying the pullback within the uptrend"


def test_record_prediction_rejects_unknown_agent():
    predictions.start_round("2026-10-20", ["NVDA"])
    with pytest.raises(ValueError):
        predictions.record_prediction("2026-10-20", "not_a_real_agent", "NVDA", 220.0, "x")


def test_record_prediction_rejects_ticker_outside_universe():
    predictions.start_round("2026-10-20", ["NVDA"])
    with pytest.raises(ValueError):
        predictions.record_prediction("2026-10-20", "technical_trader", "AVGO", 330.0, "x")


def test_record_prediction_replaces_existing_entry_from_same_agent_and_ticker():
    predictions.start_round("2026-10-20", ["NVDA"])
    predictions.record_prediction("2026-10-20", "technical_trader", "NVDA", 220.0, "first guess")
    result = predictions.record_prediction("2026-10-20", "technical_trader", "NVDA", 225.0, "revised guess")
    assert len(result["predictions"]) == 1
    assert result["predictions"][0]["predicted_close"] == 225.0
    assert result["predictions"][0]["rationale"] == "revised guess"


def test_record_prediction_keeps_separate_entries_per_agent():
    predictions.start_round("2026-10-20", ["NVDA"])
    predictions.record_prediction("2026-10-20", "technical_trader", "NVDA", 220.0, "a")
    result = predictions.record_prediction("2026-10-20", "fundamental_trader", "NVDA", 230.0, "b")
    assert len(result["predictions"]) == 2
    agents = {p["agent"] for p in result["predictions"]}
    assert agents == {"technical_trader", "fundamental_trader"}


def test_score_round_computes_error_against_actual_close(monkeypatch):
    predictions.start_round("2026-10-20", ["NVDA"])
    predictions.record_prediction("2026-10-20", "technical_trader", "NVDA", 220.0, "x")
    monkeypatch.setattr(predictions, "get_quote", lambda ticker: 200.0)
    result = predictions.score_round("2026-10-20")
    assert result["scored"][0]["actual_close"] == 200.0
    assert result["scored"][0]["error_pct"] == pytest.approx(10.0)


def test_cli_record_rejects_missing_predicted_close(monkeypatch):
    predictions.start_round("2026-10-20", ["NVDA"])
    monkeypatch.setattr("sys.argv", [
        "predictions.py", "record", "2026-10-20", "technical_trader", "NVDA", "--rationale", "x",
    ])
    with pytest.raises(SystemExit):
        predictions.main()
