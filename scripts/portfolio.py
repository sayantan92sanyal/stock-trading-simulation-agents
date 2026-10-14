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
