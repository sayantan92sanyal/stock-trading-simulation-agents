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
VALID_STANCES = ("buy", "hold", "sell")
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
            agent: {"status": "active", "stance": None, "position_summary": None, "settled_at_turn": None}
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
    if not state["turns"]:
        start_index = 0
    else:
        last_agent = state["turns"][-1]["agent"]
        start_index = (VALID_AGENTS.index(last_agent) + 1) % len(VALID_AGENTS)
    for i in range(len(VALID_AGENTS)):
        candidate = VALID_AGENTS[(start_index + i) % len(VALID_AGENTS)]
        if state["participants"][candidate]["status"] == "active":
            return candidate
    return None


def _active_count(state):
    return sum(1 for p in state["participants"].values() if p["status"] == "active")


def append_turn(debate_id, agent, stance, position_summary, argument, status):
    if agent not in VALID_AGENTS:
        raise ValueError(f"unknown agent {agent!r}, must be one of {VALID_AGENTS}")
    if stance not in VALID_STANCES:
        raise ValueError(f"stance must be one of {VALID_STANCES}, got {stance!r}")
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}, got {status!r}")

    state = show_debate(debate_id)
    if state["participants"][agent]["status"] != "active":
        raise ValueError(f"{agent!r} has already settled in this debate and cannot take another turn")

    was_lone_holdout = _active_count(state) == 1
    resolved_status = "settle" if was_lone_holdout else status

    prev_stance = state["participants"][agent]["stance"]
    stance_changed = prev_stance is not None and prev_stance != stance

    turn_number = len(state["turns"]) + 1
    turn = {
        "turn": turn_number,
        "agent": agent,
        "stance": stance,
        "position_summary": position_summary,
        "argument": argument,
        "status": resolved_status,
        "stance_changed": stance_changed,
        "forced_by_timeout": False,
        "timestamp": _now_iso(),
    }
    state["turns"].append(turn)
    state["participants"][agent]["stance"] = stance
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
    p_turn.add_argument("--stance", required=True, choices=list(VALID_STANCES))
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
                args.debate_id, args.agent, args.stance, args.position, args.argument, args.status,
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
