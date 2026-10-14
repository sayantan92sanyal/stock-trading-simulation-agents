# Stock Trading Simulation Agents

A multi-agent paper trading simulation built on Claude Code subagents. Three trader personas with distinct investment philosophies research the same ticker universe each round and make independent buy/sell/hold calls, which are executed through a single deterministic ledger. A fourth agent orchestrates the rounds, and a fifth reviews performance on request.

**Paper trading only — no real brokerage integration, no real money.**

## Architecture

- **`trading-boss`** — the orchestrator. The only agent you talk to directly. Resolves the ticker universe for a round, dispatches the three traders, executes their non-hold decisions, and reports back.
- **`technical-trader`** — decides using only price action and computed indicators (RSI, MACD, SMA, volume trend). Ignores fundamentals and news.
- **`fundamental-trader`** — decides using valuation (P/E, PEG), business quality (growth, margins, debt), and macro conditions. Ignores charts and headlines.
- **`retail-investor`** — decides using news, sentiment, and momentum, the way an engaged retail trader actually behaves. Explicit about chasing narratives.
- **`performance-reviewer`** — runs only when explicitly asked. Computes returns, a buy-and-hold benchmark, and a narrative verdict per agent.

All money math and market data access live in deterministic Python scripts, never in an LLM call:

- `scripts/indicators.py` — pure technical indicator math (SMA, EMA, RSI, MACD, volume trend).
- `scripts/market_data.py` — yfinance-backed quotes, history, indicators, fundamentals, and news.
- `scripts/portfolio.py` — the ledger. Tracks cash + holdings per agent and executes trades. Trader agents never touch this directly — only the boss does, after parsing a trader's decision.

See `docs/superpowers/specs/2026-10-13-multi-agent-stock-trading-design.md` for the full design spec and `docs/superpowers/plans/2026-10-13-multi-agent-stock-trading.md` for the implementation plan.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Run the test suite:

```bash
.venv/bin/python3 -m pytest -v
```

## Running a round

Each trader agent starts with $50,000 in virtual cash. Portfolios and trade history are gitignored (`data/`) — they're per-user local state, not part of the repo.

Talk to the `trading-boss` agent (via Claude Code's Agent/Task tool, `subagent_type: "trading-boss"`) with a request like:

> Run a trading round on AAPL, MSFT, GOOGL

or a sector/theme instead of explicit tickers:

> Run a round on energy stocks

Ask it to review performance at any point:

> Review the agents' performance so far

This appends a dated section to `data/performance/log.md` with each agent's current portfolio value, total return, a buy-and-hold benchmark, and a narrative verdict.

## Global constraints

- Data sources: `yfinance` only, no paid API keys required.
- Long-only cash equities — no shorting, margin, or options.
- Trade execution is centralized in `scripts/portfolio.py`; trader agents decide, the boss executes.
- Stock universe is supplied by the user each round — never hard-coded.
