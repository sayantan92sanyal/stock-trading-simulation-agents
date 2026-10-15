# Agent Debate Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user ask the `trading-boss` agent to run an open-ended debate among the three trader personas, with turns in strict rotation, individual opt-out ("settle"), a 5-minute wall-clock cap, and a live local browser viewer the boss auto-launches.

**Architecture:** A new deterministic ledger script (`scripts/debate.py`) owns all debate state (rotation, stance tracking, the 5-minute timeout) the same way `portfolio.py` owns money math — no LLM ever hand-rolls the transcript file. The boss runs the whole debate as one synchronous loop of foreground `Agent()` calls (no background dispatches). A small stdlib-only HTTP server (`scripts/debate_server.py`) serves a single static page (`web/viewer.html`) that polls the transcript live.

**Tech Stack:** Python 3 stdlib (`argparse`/`json`/`http.server`), `pytest`, Pillow (one-time icon generation only), Claude Code project subagents (`.claude/agents/*.md`), vanilla JS/HTML (no build step, no framework).

**Spec:** `docs/superpowers/specs/2026-10-14-agent-debate-feature-design.md`

## Global Constraints

- Debates are purely informational — never execute a trade, regardless of outcome.
- Debate topic is free text, taken verbatim from the user — never restricted to the active round's ticker universe or forced into buy/sell/hold framing.
- Participants are always exactly `technical_trader`, `fundamental_trader`, `retail_investor` — the performance reviewer never participates.
- Strict turn rotation: technical → fundamental → retail → repeat, skipping any participant who has already settled.
- Debate ends when all 3 have settled (`end_reason: "all_settled"`), or 300 seconds have elapsed since `start_time` (`end_reason: "timeout"`), whichever comes first.
- Last-holdout rule: when exactly one participant remains active, they get exactly one more turn, after which they are force-settled regardless of the `status` they submitted.
- All debate state transitions live in `scripts/debate.py`; no agent ever hand-rolls the transcript file.
- Debate transcripts live in `data/debates/<debate_id>.json`, under the existing `data/` `.gitignore` rule — never committed.
- The viewer server uses Python stdlib only (`http.server`) — no new runtime dependency. Pillow is a one-time asset-generation dependency only, not used at runtime by any other script.
- Every Bash call from an agent is a fresh shell — script invocations use `.venv/bin/python3 scripts/<script>.py ...` directly.

## Review Focus

- A trader's reply during a debate turn isn't valid JSON or is missing a required field → the boss must record it as a forced settle and continue with the remaining participants, never aborting the whole debate. Owned by Task 5 (live behavior, verified end-to-end).
- A participant is still active when the 5-minute timeout fires but has never taken a single turn → their `position_summary` must stay `null` rather than crashing or fabricating a position. Owned by Task 1.
- Two participants settle, leaving exactly one active → that participant gets exactly one more turn and is then force-settled even if they explicitly report `status: "continue"`. Owned by Task 1.
- The viewer requests a `debate_id` that doesn't exist (typo, or opened before any debate began) → the server returns a clean 404, never a stack trace; the viewer shows a friendly waiting/not-found state. Owned by Task 3.
- `append_turn` is called for an agent that has already settled (e.g. a stale or duplicate call) → rejected cleanly via `ValueError`, never silently overwriting a settled position. Owned by Task 1.

---

## Task 1: Debate ledger (`scripts/debate.py`)

**Files:**
- Create: `scripts/debate.py`
- Create: `tests/test_debate.py`

**Interfaces:**
- Produces: `start_debate(topic: str) -> dict`, `next_speaker(debate_id: str) -> str | None`, `append_turn(debate_id: str, agent: str, position_summary: str, argument: str, status: str) -> dict`, `check_timeout(debate_id: str) -> dict`, `show_debate(debate_id: str) -> dict` (raises `FileNotFoundError` if unknown), `list_debates() -> list[dict]`, module constant `VALID_AGENTS`. CLI subcommands `start`, `next-speaker`, `turn`, `check-timeout`, `show`, `list`. Consumed by Task 3 (server) and Task 5 (boss), via both direct import (tests) and CLI (boss/agents).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_debate.py`:

```python
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
    debate.append_turn(debate_id, "technical_trader", "Hold", "No setup.", "continue")
    assert debate.next_speaker(debate_id) == "fundamental_trader"
    debate.append_turn(debate_id, "fundamental_trader", "Buy", "Cheap PEG.", "continue")
    assert debate.next_speaker(debate_id) == "retail_investor"


def test_next_speaker_skips_settled_participants():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "Hold", "No setup.", "settle")
    assert debate.next_speaker(debate_id) == "fundamental_trader"
    debate.append_turn(debate_id, "fundamental_trader", "Buy", "Cheap.", "continue")
    assert debate.next_speaker(debate_id) == "retail_investor"
    debate.append_turn(debate_id, "retail_investor", "Buy", "Hype.", "continue")
    assert debate.next_speaker(debate_id) == "fundamental_trader"


def test_next_speaker_returns_none_when_all_settled():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "Hold", "a", "settle")
    debate.append_turn(debate_id, "fundamental_trader", "Hold", "b", "settle")
    debate.append_turn(debate_id, "retail_investor", "Hold", "c", "settle")
    assert debate.next_speaker(debate_id) is None


def test_append_turn_records_fields_and_updates_participant():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    result = debate.append_turn(
        debate_id, "technical_trader", "Hold for now", "RSI overbought.", "continue",
    )
    turn = result["turns"][0]
    assert turn["turn"] == 1
    assert turn["agent"] == "technical_trader"
    assert turn["position_summary"] == "Hold for now"
    assert turn["argument"] == "RSI overbought."
    assert turn["status"] == "continue"
    assert turn["stance_changed"] is False
    assert turn["forced_by_timeout"] is False
    assert result["participants"]["technical_trader"]["position_summary"] == "Hold for now"
    assert result["participants"]["technical_trader"]["status"] == "active"


def test_append_turn_settle_marks_participant_settled():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    result = debate.append_turn(debate_id, "technical_trader", "Hold", "Final.", "settle")
    assert result["participants"]["technical_trader"]["status"] == "settled"
    assert result["participants"]["technical_trader"]["settled_at_turn"] == 1


def test_append_turn_first_turn_is_never_a_stance_change():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    result = debate.append_turn(debate_id, "technical_trader", "Buy", "Setup confirmed.", "continue")
    assert result["turns"][0]["stance_changed"] is False


def test_append_turn_detects_stance_change():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "Hold", "a", "continue")
    debate.append_turn(debate_id, "fundamental_trader", "Buy", "b", "continue")
    debate.append_turn(debate_id, "retail_investor", "Buy", "c", "continue")
    result = debate.append_turn(
        debate_id, "technical_trader", "Buy", "Convinced by fundamental's point.", "continue",
    )
    assert result["turns"][-1]["stance_changed"] is True


def test_append_turn_rejects_unknown_agent():
    state = debate.start_debate("Topic")
    with pytest.raises(ValueError):
        debate.append_turn(state["debate_id"], "not_a_real_agent", "x", "y", "continue")


def test_append_turn_rejects_invalid_status():
    state = debate.start_debate("Topic")
    with pytest.raises(ValueError):
        debate.append_turn(state["debate_id"], "technical_trader", "x", "y", "maybe")


def test_append_turn_rejects_turn_from_already_settled_agent():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "Hold", "a", "settle")
    with pytest.raises(ValueError):
        debate.append_turn(debate_id, "technical_trader", "Buy", "b", "continue")


def test_append_turn_auto_finalizes_when_last_participant_settles():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "Hold", "a", "settle")
    debate.append_turn(debate_id, "fundamental_trader", "Buy", "b", "settle")
    result = debate.append_turn(debate_id, "retail_investor", "Buy", "c", "settle")
    assert result["status"] == "complete"
    assert result["end_reason"] == "all_settled"
    assert result["end_time"] is not None


def test_append_turn_forces_settle_on_lone_holdout_even_if_continue_submitted():
    state = debate.start_debate("Topic")
    debate_id = state["debate_id"]
    debate.append_turn(debate_id, "technical_trader", "Hold", "a", "settle")
    debate.append_turn(debate_id, "fundamental_trader", "Buy", "b", "settle")
    result = debate.append_turn(
        debate_id, "retail_investor", "Still buying", "One more point.", "continue",
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
    debate.append_turn(debate_id, "technical_trader", "Hold", "a", "continue")

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
    debate.append_turn(debate_id, "technical_trader", "Hold", "a", "settle")
    debate.append_turn(debate_id, "fundamental_trader", "Hold", "b", "settle")
    debate.append_turn(debate_id, "retail_investor", "Hold", "c", "settle")
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
        "--position", "p", "--argument", "a", "--status", "maybe",
    ])
    with pytest.raises(SystemExit):
        debate.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_debate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debate'`

- [ ] **Step 3: Write the implementation**

Create `scripts/debate.py`:

```python
"""Deterministic debate ledger: turn rotation, stance tracking, and the 5-minute timeout. No LLM reasoning lives here."""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

VALID_AGENTS = ["technical_trader", "fundamental_trader", "retail_investor"]
VALID_STATUSES = ("continue", "settle")
TIMEOUT_SECONDS = 300

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEBATES_DIR = DATA_DIR / "debates"


def _now():
    return datetime.now(timezone.utc)


def _now_iso():
    return _now().isoformat()


def _debate_path(debate_id):
    return DEBATES_DIR / f"{debate_id}.json"


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


def _slugify(topic):
    slug = "".join(c.lower() if c.isalnum() else "-" for c in topic)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    words = [w for w in slug.split("-") if w][:6]
    return "-".join(words) if words else "debate"


def show_debate(debate_id):
    path = _debate_path(debate_id)
    if not path.exists():
        raise FileNotFoundError(f"no debate found for {debate_id!r}")
    with open(path) as f:
        return json.load(f)


def start_debate(topic):
    if not topic or not topic.strip():
        raise ValueError("topic must not be empty")
    date_str = _now().strftime("%Y-%m-%d")
    slug = _slugify(topic)
    n = 1
    while True:
        debate_id = f"{date_str}-{slug}-{n:02d}"
        if not _debate_path(debate_id).exists():
            break
        n += 1
    state = {
        "debate_id": debate_id,
        "topic": topic,
        "status": "in_progress",
        "start_time": _now_iso(),
        "end_time": None,
        "end_reason": None,
        "participants": {
            agent: {"status": "active", "position_summary": None, "settled_at_turn": None}
            for agent in VALID_AGENTS
        },
        "turns": [],
    }
    _atomic_write(_debate_path(debate_id), state)
    return state


def next_speaker(debate_id):
    state = show_debate(debate_id)
    if state["status"] != "in_progress":
        return None
    for agent in VALID_AGENTS:
        if state["participants"][agent]["status"] == "active":
            return agent
    return None


def _active_count(state):
    return sum(1 for p in state["participants"].values() if p["status"] == "active")


def append_turn(debate_id, agent, position_summary, argument, status):
    if agent not in VALID_AGENTS:
        raise ValueError(f"unknown agent {agent!r}, must be one of {VALID_AGENTS}")
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}, got {status!r}")

    state = show_debate(debate_id)
    if state["participants"][agent]["status"] != "active":
        raise ValueError(f"{agent!r} has already settled in this debate and cannot take another turn")

    was_lone_holdout = _active_count(state) == 1
    resolved_status = "settle" if was_lone_holdout else status

    prev_position = state["participants"][agent]["position_summary"]
    stance_changed = prev_position is not None and prev_position != position_summary

    turn_number = len(state["turns"]) + 1
    turn = {
        "turn": turn_number,
        "agent": agent,
        "position_summary": position_summary,
        "argument": argument,
        "status": resolved_status,
        "stance_changed": stance_changed,
        "forced_by_timeout": False,
        "timestamp": _now_iso(),
    }
    state["turns"].append(turn)
    state["participants"][agent]["position_summary"] = position_summary
    if resolved_status == "settle":
        state["participants"][agent]["status"] = "settled"
        state["participants"][agent]["settled_at_turn"] = turn_number

    if _active_count(state) == 0:
        state["status"] = "complete"
        state["end_time"] = _now_iso()
        state["end_reason"] = "all_settled"

    _atomic_write(_debate_path(debate_id), state)
    return state


def check_timeout(debate_id):
    state = show_debate(debate_id)
    if state["status"] != "in_progress":
        return state

    started = datetime.fromisoformat(state["start_time"])
    if (_now() - started).total_seconds() < TIMEOUT_SECONDS:
        return state

    for agent, pdata in state["participants"].items():
        if pdata["status"] == "active":
            pdata["status"] = "settled"
            for turn in reversed(state["turns"]):
                if turn["agent"] == agent:
                    turn["forced_by_timeout"] = True
                    break

    state["status"] = "complete"
    state["end_time"] = _now_iso()
    state["end_reason"] = "timeout"
    _atomic_write(_debate_path(debate_id), state)
    return state


def list_debates():
    DEBATES_DIR.mkdir(parents=True, exist_ok=True)
    debates = []
    for path in DEBATES_DIR.glob("*.json"):
        with open(path) as f:
            data = json.load(f)
        debates.append({
            "debate_id": data["debate_id"],
            "topic": data["topic"],
            "status": data["status"],
            "start_time": data["start_time"],
        })
    debates.sort(key=lambda d: d["start_time"], reverse=True)
    return debates


def main():
    parser = argparse.ArgumentParser(prog="debate.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start")
    p_start.add_argument("topic")

    p_next = sub.add_parser("next-speaker")
    p_next.add_argument("debate_id")

    p_turn = sub.add_parser("turn")
    p_turn.add_argument("debate_id")
    p_turn.add_argument("agent")
    p_turn.add_argument("--position", required=True)
    p_turn.add_argument("--argument", required=True)
    p_turn.add_argument("--status", required=True, choices=list(VALID_STATUSES))

    p_timeout = sub.add_parser("check-timeout")
    p_timeout.add_argument("debate_id")

    p_show = sub.add_parser("show")
    p_show.add_argument("debate_id")

    sub.add_parser("list")

    args = parser.parse_args()

    try:
        if args.command == "start":
            print(json.dumps(start_debate(args.topic)))
        elif args.command == "next-speaker":
            print(json.dumps({"next_speaker": next_speaker(args.debate_id)}))
        elif args.command == "turn":
            print(json.dumps(append_turn(
                args.debate_id, args.agent, args.position, args.argument, args.status,
            )))
        elif args.command == "check-timeout":
            print(json.dumps(check_timeout(args.debate_id)))
        elif args.command == "show":
            print(json.dumps(show_debate(args.debate_id)))
        elif args.command == "list":
            print(json.dumps(list_debates()))
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_debate.py -v`
Expected: PASS (21 passed)

- [ ] **Step 5: Run the full test suite together**

Run: `.venv/bin/python3 -m pytest -v`
Expected: all tests across all test files pass (existing suite + the 21 new ones).

- [ ] **Step 6: Commit**

```bash
git add scripts/debate.py tests/test_debate.py
git commit -m "feat: add deterministic debate ledger with rotation, stance tracking, and timeout"
```

---

## Task 2: Persona icons

**Files:**
- Create: `scripts/generate_icons.py`
- Create: `web/icons/technical.png`, `web/icons/fundamental.png`, `web/icons/retail.png` (binary, generated by running the script)
- Modify: `requirements.txt`

**Interfaces:**
- Produces: three PNG files at `web/icons/{technical,fundamental,retail}.png`, 128×128px. Consumed by Task 3 (server serves them, viewer references them by URL).

- [ ] **Step 1: Add Pillow to requirements**

Update `requirements.txt` to:

```
pytest>=7.4
yfinance>=0.2.40
pandas>=2.0
Pillow>=10.0
```

Run: `.venv/bin/pip install -r requirements.txt`

- [ ] **Step 2: Write the icon generator**

Create `scripts/generate_icons.py`:

```python
"""One-time script: generates the three persona icons into web/icons/. Not needed at runtime by any other script."""

from pathlib import Path

from PIL import Image, ImageDraw

ICONS_DIR = Path(__file__).resolve().parent.parent / "web" / "icons"
SIZE = 128


def _blank(bg):
    return Image.new("RGB", (SIZE, SIZE), bg)


def draw_technical():
    img = _blank((16, 42, 58))
    draw = ImageDraw.Draw(img)
    bars = [(20, 90, 32, 40), (44, 90, 56, 60), (68, 90, 80, 25), (92, 90, 104, 70)]
    for x0, y0, x1, y1 in bars:
        draw.rectangle([x0, y1, x1, y0], fill=(64, 196, 212))
    draw.line([(16, 100), (40, 55), (64, 70), (88, 20), (112, 35)], fill=(255, 255, 255), width=4)
    return img


def draw_fundamental():
    img = _blank((30, 46, 24))
    draw = ImageDraw.Draw(img)
    gold = (212, 175, 55)
    draw.line([(64, 20), (64, 50)], fill=gold, width=5)
    draw.line([(24, 50), (104, 50)], fill=gold, width=5)
    draw.line([(24, 50), (12, 90)], fill=gold, width=4)
    draw.line([(24, 50), (36, 90)], fill=gold, width=4)
    draw.arc([4, 70, 44, 100], start=0, end=180, fill=gold, width=4)
    draw.line([(104, 50), (92, 90)], fill=gold, width=4)
    draw.line([(104, 50), (116, 90)], fill=gold, width=4)
    draw.arc([84, 70, 124, 100], start=0, end=180, fill=gold, width=4)
    draw.polygon([(54, 108), (74, 108), (64, 118)], fill=gold)
    return img


def draw_retail():
    img = _blank((58, 20, 16))
    draw = ImageDraw.Draw(img)
    orange = (255, 140, 60)
    draw.rounded_rectangle([16, 24, 112, 84], radius=16, outline=orange, width=5)
    draw.polygon([(36, 84), (36, 104), (56, 84)], fill=orange)
    draw.polygon(
        [(78, 40), (70, 64), (82, 60), (74, 92), (96, 56), (84, 58)],
        fill=(255, 196, 80),
    )
    return img


def main():
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    draw_technical().save(ICONS_DIR / "technical.png")
    draw_fundamental().save(ICONS_DIR / "fundamental.png")
    draw_retail().save(ICONS_DIR / "retail.png")
    print(f"Wrote 3 icons to {ICONS_DIR}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run it and verify the output**

Run: `.venv/bin/python3 scripts/generate_icons.py`
Expected: prints `Wrote 3 icons to .../web/icons`.

Run: `.venv/bin/python3 -c "from PIL import Image; [print(p, Image.open(p).size) for p in __import__('pathlib').Path('web/icons').glob('*.png')]"`
Expected: all three files print `(128, 128)` with no errors (confirms each is a valid, readable PNG).

- [ ] **Step 4: Commit**

```bash
git add requirements.txt scripts/generate_icons.py web/icons/technical.png web/icons/fundamental.png web/icons/retail.png
git commit -m "feat: add persona icon generator and generated icons"
```

---

## Task 3: Local debate viewer (`scripts/debate_server.py` + `web/viewer.html`)

**Files:**
- Create: `scripts/debate_server.py`
- Create: `web/viewer.html`
- Create: `tests/test_debate_server.py`

**Interfaces:**
- Consumes: `debate.show_debate`, `debate.list_debates` from Task 1; icon files from Task 2 (referenced by URL in `viewer.html`, not required to exist for the server's own tests to pass).
- Produces: an HTTP server exposing `GET /`, `GET /icons/<name>.png`, `GET /api/debate/<id>`, `GET /api/debates`, module-level `ICONS_DIR`, `VIEWER_HTML`, `DebateHandler`, `DEFAULT_PORT`, `serve(port)`. Consumed by Task 5 (boss auto-launches this server).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_debate_server.py`:

```python
import json
import threading
import urllib.error
import urllib.request

import pytest

import debate
import debate_server


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    monkeypatch.setattr(debate, "DEBATES_DIR", tmp_path / "debates")
    monkeypatch.setattr(debate_server, "ICONS_DIR", tmp_path / "icons")
    monkeypatch.setattr(debate_server, "VIEWER_HTML", tmp_path / "viewer.html")
    (tmp_path / "viewer.html").write_text("<html>debate viewer</html>")
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "technical.png").write_bytes(b"fakepngbytes")

    server = debate_server.ThreadingHTTPServer(("127.0.0.1", 0), debate_server.DebateHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()
    thread.join()


def _get(port, path):
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_serves_viewer_html(running_server):
    url = f"http://127.0.0.1:{running_server}/"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        assert b"debate viewer" in resp.read()


def test_serves_icon_png(running_server):
    url = f"http://127.0.0.1:{running_server}/icons/technical.png"
    with urllib.request.urlopen(url) as resp:
        assert resp.status == 200
        assert resp.read() == b"fakepngbytes"


def test_api_debates_empty_list_when_none_exist(running_server):
    status, body = _get(running_server, "/api/debates")
    assert status == 200
    assert body == []


def test_api_debate_returns_seeded_debate(running_server):
    state = debate.start_debate("Should I buy MSFT?")
    status, body = _get(running_server, f"/api/debate/{state['debate_id']}")
    assert status == 200
    assert body["topic"] == "Should I buy MSFT?"


def test_api_debate_404_for_unknown_id(running_server):
    status, body = _get(running_server, "/api/debate/does-not-exist-01")
    assert status == 404
    assert "error" in body


def test_unknown_path_returns_404(running_server):
    status, body = _get(running_server, "/not-a-real-route")
    assert status == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_debate_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debate_server'`

- [ ] **Step 3: Write the viewer page**

Create `web/viewer.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Trader Debate</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0f1115; color: #e8e8e8; margin: 0; padding: 24px; }
  h1 { font-size: 20px; margin-bottom: 4px; }
  #topic { color: #9aa; margin-bottom: 20px; }
  #status { display: flex; gap: 16px; margin-bottom: 24px; }
  .participant { flex: 1; background: #1a1d24; border-radius: 8px; padding: 12px; }
  .participant img { width: 32px; height: 32px; vertical-align: middle; border-radius: 6px; }
  .badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-left: 8px; }
  .badge.arguing { background: #2a4; color: #fff; }
  .badge.settled { background: #666; color: #fff; }
  .position { margin-top: 8px; font-size: 13px; color: #cde; }
  #transcript { display: flex; flex-direction: column; gap: 12px; }
  .turn { background: #181b21; border-radius: 8px; padding: 12px 16px; display: flex; gap: 12px; }
  .turn img { width: 28px; height: 28px; border-radius: 6px; flex-shrink: 0; }
  .turn .body { flex: 1; }
  .turn .who { font-weight: 600; font-size: 13px; }
  .turn .changed { color: #ffb84d; font-size: 11px; margin-left: 6px; }
  .turn .arg { font-size: 14px; margin-top: 4px; }
  #end-banner { margin-top: 20px; padding: 12px; border-radius: 8px; background: #26314a; display: none; }
  #waiting { color: #889; }
</style>
</head>
<body>
  <h1>Trader Debate</h1>
  <div id="topic"></div>
  <div id="waiting">Waiting for a debate to start...</div>
  <div id="status" style="display:none"></div>
  <div id="transcript"></div>
  <div id="end-banner"></div>

<script>
const ICONS = {
  technical_trader: "/icons/technical.png",
  fundamental_trader: "/icons/fundamental.png",
  retail_investor: "/icons/retail.png",
};
const LABELS = {
  technical_trader: "Technical Trader",
  fundamental_trader: "Fundamental Trader",
  retail_investor: "Retail Investor",
};

let currentDebateId = new URLSearchParams(window.location.search).get("debate");
let polling = null;

function renderStatus(participants) {
  const el = document.getElementById("status");
  el.style.display = "flex";
  el.innerHTML = Object.keys(LABELS).map(agent => {
    const p = participants[agent];
    const badgeClass = p.status === "settled" ? "settled" : "arguing";
    const position = p.position_summary ? p.position_summary : "(no position yet)";
    return `<div class="participant">
      <img src="${ICONS[agent]}"> <strong>${LABELS[agent]}</strong>
      <span class="badge ${badgeClass}">${p.status === "settled" ? "settled" : "arguing"}</span>
      <div class="position">${position}</div>
    </div>`;
  }).join("");
}

function renderTranscript(turns) {
  const el = document.getElementById("transcript");
  el.innerHTML = turns.map(t => `
    <div class="turn">
      <img src="${ICONS[t.agent]}">
      <div class="body">
        <div class="who">${LABELS[t.agent]}
          ${t.stance_changed ? '<span class="changed">changed stance</span>' : ''}
          ${t.forced_by_timeout ? '<span class="changed">cut off by timer</span>' : ''}
        </div>
        <div class="arg">${t.argument}</div>
      </div>
    </div>
  `).join("");
}

function renderEndBanner(state) {
  const el = document.getElementById("end-banner");
  if (state.status !== "complete") {
    el.style.display = "none";
    return;
  }
  el.style.display = "block";
  el.textContent = state.end_reason === "timeout"
    ? "Debate reached the 5-minute time limit."
    : "All three traders reached a final position.";
}

async function pollDebate() {
  try {
    const res = await fetch(`/api/debate/${currentDebateId}`);
    if (res.status === 404) {
      currentDebateId = null;
      return;
    }
    const state = await res.json();
    document.getElementById("waiting").style.display = "none";
    document.getElementById("topic").textContent = state.topic;
    renderStatus(state.participants);
    renderTranscript(state.turns);
    renderEndBanner(state);
    if (state.status === "complete" && polling) {
      clearInterval(polling);
      polling = setInterval(pollLatest, 5000);
    }
  } catch (e) {
    // transient fetch error; try again on next tick
  }
}

async function pollLatest() {
  if (currentDebateId) {
    pollDebate();
    return;
  }
  try {
    const res = await fetch("/api/debates");
    const debates = await res.json();
    if (debates.length > 0) {
      currentDebateId = debates[0].debate_id;
      clearInterval(polling);
      polling = setInterval(pollDebate, 1500);
      pollDebate();
    }
  } catch (e) {
    // server not up yet; keep waiting
  }
}

if (currentDebateId) {
  polling = setInterval(pollDebate, 1500);
  pollDebate();
} else {
  polling = setInterval(pollLatest, 5000);
  pollLatest();
}
</script>
</body>
</html>
```

- [ ] **Step 4: Write the server**

Create `scripts/debate_server.py`:

```python
"""Local HTTP server for the live debate viewer. Serves the static page, icons, and the debate JSON API."""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import debate as deb

ROOT = Path(__file__).resolve().parent.parent
VIEWER_HTML = ROOT / "web" / "viewer.html"
ICONS_DIR = ROOT / "web" / "icons"

DEFAULT_PORT = 8765


class DebateHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        if not path.exists():
            self._send_json(404, {"error": f"not found: {path.name}"})
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/viewer.html":
            self._send_file(VIEWER_HTML, "text/html")
        elif self.path.startswith("/icons/") and self.path.endswith(".png"):
            name = self.path[len("/icons/"):]
            self._send_file(ICONS_DIR / name, "image/png")
        elif self.path == "/api/debates":
            self._send_json(200, deb.list_debates())
        elif self.path.startswith("/api/debate/"):
            debate_id = self.path[len("/api/debate/"):]
            try:
                self._send_json(200, deb.show_debate(debate_id))
            except FileNotFoundError:
                self._send_json(404, {"error": f"no debate found for {debate_id!r}"})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        pass


def serve(port=DEFAULT_PORT):
    server = ThreadingHTTPServer(("127.0.0.1", port), DebateHandler)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(prog="debate_server.py")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    print(f"Serving debate viewer on http://localhost:{args.port}/")
    serve(args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_debate_server.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Run the full test suite together**

Run: `.venv/bin/python3 -m pytest -v`
Expected: all tests across all test files pass.

- [ ] **Step 7: Manual smoke test against the real icons**

Run: `.venv/bin/python3 scripts/debate_server.py &` then, once it prints the "Serving..." line: `curl -s http://localhost:8765/icons/technical.png -o /tmp/t.png && .venv/bin/python3 -c "from PIL import Image; print(Image.open('/tmp/t.png').size)"`
Expected: prints `(128, 128)`, confirming the server serves the real generated icon from Task 2. Then stop the server: `kill %1`.

- [ ] **Step 8: Commit**

```bash
git add scripts/debate_server.py web/viewer.html tests/test_debate_server.py
git commit -m "feat: add local debate viewer server and web page"
```

---

## Task 4: Trader agent debate mode

**Files:**
- Modify: `.claude/agents/technical-trader.md`
- Modify: `.claude/agents/fundamental-trader.md`
- Modify: `.claude/agents/retail-investor.md`

**Interfaces:**
- Consumes: the debate JSON shape from Task 1 (`debate_id`, transcript `turns`).
- Produces: each trader, when given a debate-mode prompt, replies with exactly one JSON block `{"agent": "<id>", "debate_id": "<id>", "position_summary": str, "argument": str, "status": "continue"|"settle"}`. Consumed by Task 5 (boss).

- [ ] **Step 1: Add Debate mode to the technical trader**

In `.claude/agents/technical-trader.md`, append after the file's final line (`` `sizing` is required for `buy` and `sell` actions and omitted for `hold`. You do not execute trades yourself — you only decide and report. Do not call `portfolio.py trade`; that is the orchestrator's job. ``):

```markdown

## Debate mode

You are sometimes invoked by the trading-boss to take part in an open-ended debate instead of a normal trading round. You'll know it's a debate because the prompt gives you: a debate topic, a `debate_id`, and the full transcript of the debate so far (every turn taken, by whom, their position, and their argument).

1. Read the whole transcript. If this is your first turn, you have nothing to rebut yet — just state your opening position using only technical analysis (indicators, price action, volume), exactly as you would in a normal round.
2. If it is not your first turn, decide honestly whether anything said since your last turn actually changes your view. If you are genuinely persuaded, say so explicitly in your argument (e.g. "I'm now leaning toward X because of [agent]'s point about Y") rather than silently changing your stated position with no acknowledgment. You are never required to change your mind — only do so if the argument is genuinely compelling on technical grounds.
3. Produce exactly one new argument from your technical lens, engaging the other participants' specific points where relevant (not just repeating your opening case word-for-word). Pull fresh indicators via `.venv/bin/python3 scripts/market_data.py indicators <TICKER> --period 1y` if the topic concerns a specific ticker and you haven't already checked it this debate.
4. Decide `continue` (you want to hear more / have more to say) or `settle` (no further argument will change your position in this debate). Settling still requires your `argument` field to contain a real final statement, never a blank or placeholder.
5. Your final reply must contain **exactly one JSON code block and nothing else**:

```json
{
  "agent": "technical_trader",
  "debate_id": "<the debate_id you were given>",
  "position_summary": "Hold — RSI still overbought, no confirming volume",
  "argument": "RSI14 is still at 73 with volume_trend only 0.4x — I'm not chasing this without confirmation, even after hearing the fundamental case.",
  "status": "continue"
}
```
```

- [ ] **Step 2: Add Debate mode to the fundamental trader**

In `.claude/agents/fundamental-trader.md`, append after the same closing sentence:

```markdown

## Debate mode

You are sometimes invoked by the trading-boss to take part in an open-ended debate instead of a normal trading round. You'll know it's a debate because the prompt gives you: a debate topic, a `debate_id`, and the full transcript of the debate so far (every turn taken, by whom, their position, and their argument).

1. Read the whole transcript. If this is your first turn, you have nothing to rebut yet — just state your opening position using only valuation, business quality, and macro reasoning, exactly as you would in a normal round.
2. If it is not your first turn, decide honestly whether anything said since your last turn actually changes your view. If you are genuinely persuaded, say so explicitly in your argument (e.g. "I'm now leaning toward X because of [agent]'s point about Y") rather than silently changing your stated position with no acknowledgment. You are never required to change your mind — only do so if the argument is genuinely compelling on fundamentals/macro grounds.
3. Produce exactly one new argument from your fundamentals lens, engaging the other participants' specific points where relevant (not just repeating your opening case word-for-word). Pull fresh fundamentals via `.venv/bin/python3 scripts/market_data.py fundamentals <TICKER>` if the topic concerns a specific ticker and you haven't already checked it this debate.
4. Decide `continue` (you want to hear more / have more to say) or `settle` (no further argument will change your position in this debate). Settling still requires your `argument` field to contain a real final statement, never a blank or placeholder.
5. Your final reply must contain **exactly one JSON code block and nothing else**:

```json
{
  "agent": "fundamental_trader",
  "debate_id": "<the debate_id you were given>",
  "position_summary": "Buy — PEG 0.28 against 106% revenue growth is too cheap to ignore",
  "argument": "Even granting the technical trader's overbought point, a PEG this low against this growth rate is a structural mispricing, not noise — I'd rather be early than wait for a chart signal that may never come.",
  "status": "settle"
}
```
```

- [ ] **Step 3: Add Debate mode to the retail investor**

In `.claude/agents/retail-investor.md`, append after the same closing sentence:

```markdown

## Debate mode

You are sometimes invoked by the trading-boss to take part in an open-ended debate instead of a normal trading round. You'll know it's a debate because the prompt gives you: a debate topic, a `debate_id`, and the full transcript of the debate so far (every turn taken, by whom, their position, and their argument).

1. Read the whole transcript. If this is your first turn, you have nothing to rebut yet — just state your opening position using only news, sentiment, and momentum, exactly as you would in a normal round.
2. If it is not your first turn, decide honestly whether anything said since your last turn actually changes your view. If you are genuinely persuaded, say so explicitly in your argument (e.g. "okay, [agent]'s point about Y actually changes things for me") rather than silently changing your stated position with no acknowledgment. You are never required to change your mind — only do so if the argument genuinely shifts the narrative for you.
3. Produce exactly one new argument from your news/sentiment lens, engaging the other participants' specific points where relevant (not just repeating your opening case word-for-word). Pull fresh news/quotes via `.venv/bin/python3 scripts/market_data.py news <TICKER>` or `.venv/bin/python3 scripts/market_data.py quote <TICKER>`, or WebSearch, if the topic concerns a specific ticker and you haven't already checked it this debate.
4. Decide `continue` (you want to hear more / have more to say) or `settle` (no further argument will change your position in this debate). Settling still requires your `argument` field to contain a real final statement, never a blank or placeholder.
5. Your final reply must contain **exactly one JSON code block and nothing else**:

```json
{
  "agent": "retail_investor",
  "debate_id": "<the debate_id you were given>",
  "position_summary": "Buy — everyone's talking about this catalyst, don't want to miss the move",
  "argument": "I hear the fundamental case, but honestly the headline momentum here is what's going to move the stock in the next two weeks regardless of PEG ratios — I'm sticking with buy.",
  "status": "settle"
}
```
```

- [ ] **Step 4: Live-verify each trader's debate-mode output contract**

Using the Agent tool, call with `subagent_type: "technical-trader"`, `description: "Test debate mode"`, `run_in_background: false`, and this prompt:

```
This is DEBATE MODE, not a normal trading round.

Topic: Should I buy MSFT right now?
debate_id: test-debate-01

Transcript so far:
[]

Respond per your Debate mode instructions. This is your first turn.
```

Expected: the reply is exactly one JSON code block with keys `agent` (`"technical_trader"`), `debate_id` (`"test-debate-01"`), `position_summary`, `argument` (citing concrete indicator numbers), and `status` (`"continue"` or `"settle"`).

Repeat with `subagent_type: "fundamental-trader"` (expect `"agent": "fundamental_trader"`, argument citing fundamentals) and `subagent_type: "retail-investor"` (expect `"agent": "retail_investor"`, argument citing news/sentiment), using the same prompt shape.

- [ ] **Step 5: Commit**

```bash
git add .claude/agents/technical-trader.md .claude/agents/fundamental-trader.md .claude/agents/retail-investor.md
git commit -m "feat: add debate mode to the three trader personas"
```

---

## Task 5: Boss debate orchestration and end-to-end verification

**Files:**
- Modify: `.claude/agents/trading-boss.md`

**Interfaces:**
- Consumes: `scripts/debate.py` CLI (Task 1), `scripts/debate_server.py` (Task 3), each trader's Debate mode contract (Task 4).
- Produces: the boss agent, when asked to run a debate, drives the full loop and reports a final summary.

- [ ] **Step 1: Add the debate orchestration section**

In `.claude/agents/trading-boss.md`, append after the file's final line (`` - If a `portfolio.py trade` call is rejected, surface the exact reason to the user; never retry an order with different sizing on an agent's behalf without being asked. ``):

```markdown

## Running a debate

When the user asks for a debate (e.g. "I want to see a debate on whether I should buy MSFT", "let's debate rotating from tech to defense"), run this entirely yourself, synchronously, inside this one turn — do not dispatch any background `Agent()` calls for debate turns.

1. **Start the debate.** Run via Bash: `.venv/bin/python3 scripts/debate.py start "<topic>"` using the user's topic verbatim (don't rephrase it into a different question). Note the `debate_id` from the result.
2. **Launch the viewer if it isn't already running.** Check via Bash: `curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/api/debates`. If this does not print `200`, start the server detached: `nohup .venv/bin/python3 scripts/debate_server.py > /tmp/debate_server.log 2>&1 & disown`. Either way, then run: `open "http://localhost:8765/?debate=<debate_id>"` (substituting the real debate_id) to open the user's browser to this debate.
3. **Loop until the debate ends:**
   a. Run `.venv/bin/python3 scripts/debate.py check-timeout <debate_id>`. If the result's `"status"` is `"complete"`, stop looping.
   b. Run `.venv/bin/python3 scripts/debate.py next-speaker <debate_id>`. If the result's `"next_speaker"` is `null`, stop looping.
   c. Look up that agent id's subagent name from the "Agent ids and portfolio ids" table above (e.g. `technical_trader` → `technical-trader`). Run `.venv/bin/python3 scripts/debate.py show <debate_id>` to get the full transcript. Using the Agent tool with `run_in_background: false`, dispatch that subagent with a prompt stating this is **debate mode**, giving the topic, the `debate_id`, and the full transcript JSON, and telling it to respond per its own `## Debate mode` instructions.
   d. Parse the trader's final JSON block (`position_summary`, `argument`, `status`). If it cannot be parsed, or is missing any of those three fields, call `.venv/bin/python3 scripts/debate.py turn <debate_id> <agent_id> --position "<that agent's most recent position from the transcript, or 'unclear' if it has none yet>" --argument "Could not parse this agent's debate reply; treating as settled." --status settle` and continue the loop — never abort the whole debate over one bad reply. Otherwise call `.venv/bin/python3 scripts/debate.py turn <debate_id> <agent_id> --position "<position_summary>" --argument "<argument>" --status <continue|settle>`.
   e. Go back to step (a).
4. **Report the outcome.** Run `.venv/bin/python3 scripts/debate.py show <debate_id>` for the final state. Tell the user: each participant's final `position_summary` (if a participant's is `null`, say it never got a turn before time ran out), whether the debate ended because everyone settled or because it hit the 5-minute limit, and that the full transcript is in the already-open browser tab (or give them the URL `http://localhost:8765/?debate=<debate_id>` if they need to reopen it).
```

- [ ] **Step 2: Run a full end-to-end debate**

Using the Agent tool, call with `subagent_type: "trading-boss"`, `description: "Test full debate"`, `run_in_background: false`, and this prompt:

```
I want to see a debate on whether I should buy NVDA right now.
```

Expected: the boss starts a debate, launches the viewer (or confirms one was already running), runs the turn loop to completion, and reports each trader's final position and the end reason. This may take up to 5 minutes of wall-clock time if the traders keep disagreeing.

- [ ] **Step 3: Verify the resulting transcript file**

Run: `.venv/bin/python3 scripts/debate.py list` to find the debate id from Step 2, then `.venv/bin/python3 scripts/debate.py show <debate_id>`.
Expected: `status` is `"complete"`, `end_reason` is `"all_settled"` or `"timeout"`, every participant that spoke has a non-null `position_summary`, and `turns` contains at least 3 entries (one per participant's opening position) in rotation order.

- [ ] **Step 4: Verify the viewer served it live**

Run: `curl -s http://localhost:8765/api/debate/<debate_id>` (the same id from Step 3).
Expected: returns the same JSON as `scripts/debate.py show <debate_id>`, confirming the server was reachable and serving this debate while it ran.

- [ ] **Step 5: Clean up test debate data**

The debate created in Step 2 was a real test run to prove the pipeline works — remove it so the user's first real debate starts from a clean `data/debates/`:

```bash
rm -rf data/debates
```

Confirm it's gone: `ls data/` should not show a `debates` entry. The next debate the boss starts will recreate the directory automatically.

- [ ] **Step 6: Commit**

```bash
git add .claude/agents/trading-boss.md
git commit -m "feat: add debate orchestration to the trading boss"
```
