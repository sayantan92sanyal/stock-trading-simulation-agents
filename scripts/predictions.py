"""Deterministic closing-price prediction ledger. No LLM reasoning lives here."""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_data import get_quote

VALID_AGENTS = ["technical_trader", "fundamental_trader", "retail_investor"]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PREDICTIONS_DIR = DATA_DIR / "predictions"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _predictions_path(date):
    return PREDICTIONS_DIR / f"{date}.json"


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


def start_round(date, tickers):
    if not tickers:
        raise ValueError("tickers must not be empty")
    path = _predictions_path(date)
    if path.exists():
        with open(path) as f:
            return {"status": "already_started", "round": json.load(f)}
    round_data = {
        "date": date,
        "tickers": list(tickers),
        "created_at": _now_iso(),
        "predictions": [],
    }
    _atomic_write(path, round_data)
    return {"status": "created", "round": round_data}


def show_round(date):
    path = _predictions_path(date)
    if not path.exists():
        raise FileNotFoundError(f"no prediction round found for {date!r}; run start first")
    with open(path) as f:
        return json.load(f)


def record_prediction(date, agent, ticker, predicted_close, rationale):
    if agent not in VALID_AGENTS:
        raise ValueError(f"unknown agent {agent!r}, must be one of {VALID_AGENTS}")
    round_data = show_round(date)
    if ticker not in round_data["tickers"]:
        raise ValueError(f"ticker {ticker!r} is not in this round's universe {round_data['tickers']}")

    round_data["predictions"] = [
        p for p in round_data["predictions"]
        if not (p["agent"] == agent and p["ticker"] == ticker)
    ]
    round_data["predictions"].append({
        "agent": agent,
        "ticker": ticker,
        "predicted_close": float(predicted_close),
        "rationale": rationale,
        "timestamp": _now_iso(),
    })
    _atomic_write(_predictions_path(date), round_data)
    return round_data


def score_round(date):
    round_data = show_round(date)
    actuals = {ticker: get_quote(ticker) for ticker in round_data["tickers"]}
    scored = []
    for p in round_data["predictions"]:
        actual = actuals.get(p["ticker"])
        error_pct = (p["predicted_close"] - actual) / actual * 100 if actual else None
        scored.append({**p, "actual_close": actual, "error_pct": error_pct})
    return {"date": round_data["date"], "tickers": round_data["tickers"], "scored": scored}


def main():
    parser = argparse.ArgumentParser(prog="predictions.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start")
    p_start.add_argument("date")
    p_start.add_argument("tickers", nargs="+")

    p_record = sub.add_parser("record")
    p_record.add_argument("date")
    p_record.add_argument("agent")
    p_record.add_argument("ticker")
    p_record.add_argument("--predicted-close", required=True, type=float)
    p_record.add_argument("--rationale", required=True)

    p_show = sub.add_parser("show")
    p_show.add_argument("date")

    p_score = sub.add_parser("score")
    p_score.add_argument("date")

    args = parser.parse_args()

    try:
        if args.command == "start":
            print(json.dumps(start_round(args.date, args.tickers)))
        elif args.command == "record":
            print(json.dumps(record_prediction(
                args.date, args.agent, args.ticker, args.predicted_close, args.rationale,
            )))
        elif args.command == "show":
            print(json.dumps(show_round(args.date)))
        elif args.command == "score":
            print(json.dumps(score_round(args.date)))
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
