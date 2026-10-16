from datetime import datetime, timedelta, timezone

import pytest

import debate


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(debate, "DEBATES_DIR", tmp_path / "debates")
    yield


def test_start_debate_creates_three_active_participants():
    state = debate.start_debate("Should I buy MSFT?")
    assert state["status"] == "in_progress"
    assert state["topic"] == "Should I buy MSFT?"
    assert set(state["participants"].keys()) == {
        "technical_trader", "fundamental_trader", "retail_investor",
    }
    for p in state["participants"].values():
        assert p["status"] == "active"
        assert p["stance"] is None
        assert p["conviction"] is None
        assert p["position_summary"] is None
        assert p["settled_at_turn"] is None
    assert state["turns"] == []
    assert state["end_time"] is None
    assert state["end_reason"] is None


def test_start_debate_rejects_empty_topic():
    with pytest.raises(ValueError):
        debate.start_debate("")
    with pytest.raises(ValueError):
        debate.start_debate("   ")


def test_next_speaker_follows_rotation_order():
    state = debate.start_debate("Energy sector rotation?")
    debate_id = state["debate_id"]
    assert debate.next_speaker(debate_id) == "technical_trader"
    debate.append_turn(debate_id, "technical_trader", "hold", "medium", "Hold", "No setup.", "continue")
    assert debate.next_speaker(debate_id) == "fundamental_trader"
    debate.append_turn(debate_id, "fundamental_trader", "buy", "high", "Buy", "Cheap PEG.", "continue")
    assert debate.next_speaker(debate_id) == "retail_investor"


def test_next_speaker_skips_settled_participants():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "hold", "medium", "Hold", "No setup.", "settle")
    assert debate.next_speaker(debate_id) == "fundamental_trader"
    debate.append_turn(debate_id, "fundamental_trader", "buy", "high", "Buy", "Cheap.", "continue")
    assert debate.next_speaker(debate_id) == "retail_investor"
    debate.append_turn(debate_id, "retail_investor", "buy", "medium", "Buy", "Hype.", "continue")
    assert debate.next_speaker(debate_id) == "fundamental_trader"


def test_next_speaker_returns_none_when_all_settled():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "hold", "low", "Hold", "a", "settle")
    debate.append_turn(debate_id, "fundamental_trader", "hold", "low", "Hold", "b", "settle")
    debate.append_turn(debate_id, "retail_investor", "hold", "low", "Hold", "c", "settle")
    assert debate.next_speaker(debate_id) is None


def test_append_turn_records_fields_and_updates_participant():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    result = debate.append_turn(
        debate_id, "technical_trader", "hold", "medium", "Hold for now", "RSI overbought.", "continue",
    )
    turn = result["turns"][0]
    assert turn["turn"] == 1
    assert turn["agent"] == "technical_trader"
    assert turn["stance"] == "hold"
    assert turn["conviction"] == "medium"
    assert turn["position_summary"] == "Hold for now"
    assert turn["argument"] == "RSI overbought."
    assert turn["status"] == "continue"
    assert turn["stance_changed"] is False
    assert turn["forced_by_timeout"] is False
    assert result["participants"]["technical_trader"]["stance"] == "hold"
    assert result["participants"]["technical_trader"]["conviction"] == "medium"
    assert result["participants"]["technical_trader"]["position_summary"] == "Hold for now"
    assert result["participants"]["technical_trader"]["status"] == "active"


def test_append_turn_settle_marks_participant_settled():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    result = debate.append_turn(debate_id, "technical_trader", "hold", "low", "Hold", "Final.", "settle")
    assert result["participants"]["technical_trader"]["status"] == "settled"
    assert result["participants"]["technical_trader"]["settled_at_turn"] == 1


def test_append_turn_first_turn_is_never_a_stance_change():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    result = debate.append_turn(debate_id, "technical_trader", "buy", "high", "Buy", "Setup confirmed.", "continue")
    assert result["turns"][0]["stance_changed"] is False


def test_append_turn_detects_stance_change():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "hold", "medium", "Hold", "a", "continue")
    debate.append_turn(debate_id, "fundamental_trader", "buy", "high", "Buy", "b", "continue")
    debate.append_turn(debate_id, "retail_investor", "buy", "medium", "Buy", "c", "continue")
    result = debate.append_turn(
        debate_id, "technical_trader", "buy", "medium", "Buy", "Convinced by fundamental's point.", "continue",
    )
    assert result["turns"][-1]["stance_changed"] is True


def test_append_turn_reworded_position_with_same_stance_is_not_a_stance_change():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(
        debate_id, "technical_trader", "hold", "medium",
        "Hold, not a fresh buy here - strong uptrend but RSI is overbought", "a", "continue",
    )
    debate.append_turn(debate_id, "fundamental_trader", "hold", "medium", "Hold", "b", "continue")
    debate.append_turn(debate_id, "retail_investor", "buy", "medium", "Buy", "c", "continue")
    result = debate.append_turn(
        debate_id, "technical_trader", "hold", "high",
        "Hold - RSI14 71.2 overbought and volume unconfirmed", "Still overbought.", "continue",
    )
    assert result["turns"][-1]["stance_changed"] is False


def test_append_turn_rejects_unknown_agent():
    state = debate.start_debate("Topic")
    with pytest.raises(ValueError):
        debate.append_turn(state["debate_id"], "not_a_real_agent", "hold", "medium", "x", "y", "continue")


def test_append_turn_rejects_invalid_stance():
    state = debate.start_debate("Topic")
    with pytest.raises(ValueError):
        debate.append_turn(state["debate_id"], "technical_trader", "bullish", "medium", "x", "y", "continue")


def test_append_turn_rejects_invalid_conviction():
    state = debate.start_debate("Topic")
    with pytest.raises(ValueError):
        debate.append_turn(state["debate_id"], "technical_trader", "hold", "super-sure", "x", "y", "continue")


def test_append_turn_rejects_invalid_status():
    state = debate.start_debate("Topic")
    with pytest.raises(ValueError):
        debate.append_turn(state["debate_id"], "technical_trader", "hold", "medium", "x", "y", "maybe")


def test_append_turn_rejects_turn_from_already_settled_agent():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "hold", "medium", "Hold", "a", "settle")
    with pytest.raises(ValueError):
        debate.append_turn(debate_id, "technical_trader", "buy", "medium", "Buy", "b", "continue")


def test_append_turn_auto_finalizes_when_last_participant_settles():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "hold", "medium", "Hold", "a", "settle")
    debate.append_turn(debate_id, "fundamental_trader", "buy", "high", "Buy", "b", "settle")
    result = debate.append_turn(debate_id, "retail_investor", "buy", "high", "Buy", "c", "settle")
    assert result["status"] == "complete"
    assert result["end_reason"] == "all_settled"
    assert result["end_time"] is not None


def test_append_turn_forces_settle_on_lone_holdout_even_if_continue_submitted():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "hold", "medium", "Hold", "a", "settle")
    debate.append_turn(debate_id, "fundamental_trader", "buy", "high", "Buy", "b", "settle")
    result = debate.append_turn(
        debate_id, "retail_investor", "buy", "high", "Still buying", "One more point.", "continue",
    )
    assert result["turns"][-1]["status"] == "settle"
    assert result["participants"]["retail_investor"]["status"] == "settled"
    assert result["status"] == "complete"
    assert result["end_reason"] == "all_settled"


def test_check_timeout_is_noop_before_300_seconds():
    state = debate.start_debate("Topic")
    result = debate.check_timeout(state["debate_id"])
    assert result["status"] == "in_progress"


def test_check_timeout_finalizes_after_300_seconds(monkeypatch):
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "hold", "medium", "Hold", "a", "continue")

    future = datetime.now(timezone.utc) + timedelta(seconds=301)
    monkeypatch.setattr(debate, "_now", lambda: future)

    result = debate.check_timeout(debate_id)
    assert result["status"] == "complete"
    assert result["end_reason"] == "timeout"
    assert result["participants"]["technical_trader"]["status"] == "settled"
    assert result["participants"]["fundamental_trader"]["status"] == "settled"
    assert result["participants"]["retail_investor"]["status"] == "settled"
    assert result["turns"][0]["forced_by_timeout"] is True


def test_check_timeout_participant_with_no_turns_stays_null_position(monkeypatch):
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]

    future = datetime.now(timezone.utc) + timedelta(seconds=301)
    monkeypatch.setattr(debate, "_now", lambda: future)

    result = debate.check_timeout(debate_id)
    assert result["status"] == "complete"
    assert result["end_reason"] == "timeout"
    assert result["participants"]["technical_trader"]["position_summary"] is None


def test_check_timeout_is_noop_once_already_complete():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "hold", "medium", "Hold", "a", "settle")
    debate.append_turn(debate_id, "fundamental_trader", "hold", "medium", "Hold", "b", "settle")
    debate.append_turn(debate_id, "retail_investor", "hold", "medium", "Hold", "c", "settle")
    result = debate.check_timeout(debate_id)
    assert result["end_reason"] == "all_settled"


def test_show_debate_raises_for_unknown_id():
    with pytest.raises(FileNotFoundError):
        debate.show_debate("does-not-exist-01")


def test_list_debates_returns_newest_first():
    d1 = debate.start_debate("First topic")
    d2 = debate.start_debate("Second topic")
    debates = debate.list_debates()
    ids = [d["debate_id"] for d in debates]
    assert ids[0] == d2["debate_id"]
    assert ids[1] == d1["debate_id"]


def test_cli_turn_rejects_invalid_status(monkeypatch):
    state = debate.start_debate("Topic")
    monkeypatch.setattr("sys.argv", [
        "debate.py", "turn", state["debate_id"], "technical_trader",
        "--stance", "hold", "--conviction", "medium", "--position", "p", "--argument", "a", "--status", "maybe",
    ])
    with pytest.raises(SystemExit):
        debate.main()


def test_cli_turn_rejects_invalid_stance(monkeypatch):
    state = debate.start_debate("Topic")
    monkeypatch.setattr("sys.argv", [
        "debate.py", "turn", state["debate_id"], "technical_trader",
        "--stance", "bullish", "--conviction", "medium", "--position", "p", "--argument", "a", "--status", "continue",
    ])
    with pytest.raises(SystemExit):
        debate.main()


def test_cli_turn_rejects_invalid_conviction(monkeypatch):
    state = debate.start_debate("Topic")
    monkeypatch.setattr("sys.argv", [
        "debate.py", "turn", state["debate_id"], "technical_trader",
        "--stance", "hold", "--conviction", "super-sure", "--position", "p", "--argument", "a", "--status", "continue",
    ])
    with pytest.raises(SystemExit):
        debate.main()
