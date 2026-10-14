# Multi-Agent Paper Trading System — Design Spec

Date: 2026-10-13

## Overview & Goals

Build six Claude Code subagents that simulate three competing trading
styles against the same market, under one orchestrator, with a reviewer
that logs how each style actually performed and why. This is a paper
trading simulation: no real money, no brokerage account. Each trader
agent manages a virtual cash + holdings ledger and "trades" against real,
current market data (via yfinance), so returns are realistic even though
execution is simulated.

The point is to compare trading philosophies (technical vs. fundamental
vs. retail/sentiment-driven) head to head over repeated rounds, with a
durable, auditable record of decisions and outcomes.

## Non-Goals

- No real brokerage integration (no Alpaca, IBKR, etc.).
- No continuous/scheduled automation — rounds run when the user tells
  the boss agent to run one.
- No fixed stock universe baked into the system — the user supplies the
  universe (explicit tickers, or a sector/theme the boss resolves to
  tickers) each time they request a round.
- No options, shorting, margin, or leverage — long-only cash equities for
  v1.

## Architecture Overview

Six pieces: five Claude Code subagents (boss, three traders, reviewer)
plus deterministic Python helper scripts that agents call via Bash. The
scripts own all money math and all external data fetching; agents own
reasoning and judgment only.

```
User
  │  "run a round on tech stocks: ..."  /  "review performance so far"
  ▼
Boss Agent (orchestrator)
  │
  ├─ resolves ticker universe (own knowledge + WebSearch if needed)
  ├─ spawns in parallel ──► Technical Trader Agent  ─┐
  │                    ──► Fundamental Trader Agent ─┼─► decisions
  │                    ──► Retail Investor Agent    ─┘
  │
  ├─ executes each decision via scripts/portfolio.py (validates, records)
  │
  └─ on separate explicit request ──► Performance Reviewer Agent
                                         (reads all trade logs +
                                          portfolio history, computes
                                          returns, appends to
                                          data/performance/log.md)
```

## Agents

All agents are project-level Claude Code subagents defined in
`.claude/agents/*.md` (YAML frontmatter + system prompt).

### 1. Boss Agent (`trading-boss`)

- **Role**: Takes the user's instruction, resolves the stock universe for
  the round, spawns the three trader agents in parallel (they are
  independent — no shared state, so no reason to serialize them),
  collects each one's structured decisions, executes trades for each via
  `portfolio.py`, and reports a round summary back to the user. Also
  responsible for invoking the Performance Reviewer agent when the user
  explicitly asks for a review.
- **Tools**: `Agent`, `Bash`, `Read`, `Write`, `WebSearch` (to resolve
  ambiguous sector/theme requests into concrete tickers when needed).
- **Input**: user instruction (free text — may be explicit tickers or a
  sector/theme description).
- **Output**: round summary (per agent: decisions made, trades executed
  or rejected and why, resulting portfolio value).

### 2. Technical Trader Agent (`technical-trader`)

- **Role**: Identifies quick-return setups using only quantitative
  technical signals — price action, momentum, volume, computed
  indicators. Explicitly does not use fundamentals or news sentiment as
  a basis for decisions. Skeptical of narrative, trusts numbers.
- **Tools**: `Bash` (for `scripts/market_data.py indicators` /
  `scripts/portfolio.py`), `Read`, `Write`.
- **Input**: ticker universe for the round, its own current portfolio
  state.
- **Output**: per-ticker decision — `buy` / `sell` / `hold`, size (shares
  or % of available cash), and a rationale citing the specific indicator
  values that drove the call (e.g. "RSI14 at 28, oversold bounce off
  50-day SMA, volume +40% vs. 20-day avg").

### 3. Fundamental Trader Agent (`fundamental-trader`)

- **Role**: Judges valuation (over/undervalued) and business quality
  (growth, margins, debt) using fundamentals data, plus macro/economic
  context, to decide what to hold for the medium/long term. Not
  interested in short-term price action.
- **Tools**: `Bash` (for `scripts/market_data.py fundamentals`),
  `WebSearch` (macro/economic conditions, sector outlook), `Read`,
  `Write`.
- **Input**: ticker universe for the round, its own current portfolio
  state.
- **Output**: per-ticker decision with rationale citing valuation
  metrics (P/E, PEG, growth rate, margins) and macro reasoning.

### 4. Retail Investor Agent (`retail-investor`)

- **Role**: Mimics a retail investor — leans on recent news, sentiment,
  hype, and recent price jumps/momentum rather than deep analysis. Some
  baseline market literacy, but decisions are narrative- and
  momentum-driven.
- **Tools**: `Bash` (for `scripts/market_data.py quote` / `news` — recent
  price moves and ticker-specific headlines), `WebSearch` (broader
  news/sentiment/hype), `Read`, `Write`.
- **Input**: ticker universe for the round, its own current portfolio
  state.
- **Output**: per-ticker decision with rationale citing news/sentiment
  and recent price action ("up 12% this week on AI partnership news").

### 5. Performance Reviewer Agent (`performance-reviewer`)

- **Role**: On explicit request only (not automatic per round), reads
  every trade log and portfolio snapshot since the last review across
  all three agents, computes realized + unrealized returns and a
  buy-and-hold benchmark comparison, and writes a dated entry to
  `data/performance/log.md` per agent: the numbers, plus a narrative
  verdict comparing what the agent said at trade time against what
  actually happened since (what it got right, what it got wrong, and
  why, in plain terms).
- **Tools**: `Bash` (for `scripts/portfolio.py history` /
  `scripts/market_data.py quote`), `Read`, `Write`.
- **Input**: implicit — reads all three agents' state and logs.
- **Output**: appended markdown section(s) in
  `data/performance/log.md`.

### 6. Orchestration summary

The "boss" (#1) is the orchestration agent described above. It is the
only agent the user talks to directly; it decides when to run traders
and when to run the reviewer.

## Data Flow

### Trading round

1. User instructs the boss (e.g. "run a round on oil and gas stocks:
   XOM, CVX, COP" or "run a round on tech stocks" with no explicit
   tickers).
2. Boss resolves the universe to concrete tickers (if the user didn't
   give exact tickers, boss uses its own knowledge, confirmed/refreshed
   via WebSearch if needed) and assigns a `round_id` (e.g.
   `2026-10-13-oilgas-01`).
3. Boss spawns all three trader agents in parallel, each given: the
   round's ticker list, its own agent id (so it reads/writes its own
   portfolio file), and the round id.
4. Each trader agent:
   a. Reads its current portfolio via `portfolio.py show <agent>`.
   b. Fetches whatever data its persona needs.
   c. Returns a structured decision list:
      `[{ticker, action, qty_or_pct, rationale}, ...]`
      (`hold` entries may be omitted or included for completeness).
5. Boss executes each non-hold decision via `portfolio.py trade <agent>
   <ticker> <buy|sell> --shares/--cash-amount/--pct-cash ... --round-id
   ID --rationale "..."`, passing through whichever sizing the trader
   agent chose. The script validates (sufficient cash / sufficient
   shares) and either executes and appends a trade log entry, or rejects
   and appends a rejected-order log entry with the reason. Rejections
   are surfaced back to the user in the round summary — they are not
   silently dropped.
6. Boss reports a round summary: per agent, what was decided, what
   executed vs. was rejected (and why), and resulting portfolio value.

### Performance review (on-demand)

1. User instructs the boss (or the reviewer, if invoked directly) to
   review performance.
2. Reviewer reads all three agents' portfolio files and full trade logs.
3. For each agent, for each trade since the last review, reviewer fetches
   the current price of the traded ticker and computes the paper
   gain/loss since that trade, plus the agent's overall portfolio return
   vs. starting $50,000 and vs. a simple equal-weight buy-and-hold
   benchmark over the same universe and time window.
4. Reviewer appends a dated section to `data/performance/log.md` per
   agent: metrics table + narrative (what the agent's stated rationale
   got right/wrong, in light of what actually happened).

## State & Persistence

Flat JSON / JSONL / Markdown files under `data/`. No database.

### `data/portfolios/{agent}.json`

```json
{
  "agent": "technical_trader",
  "starting_cash": 50000.00,
  "cash": 44084.00,
  "holdings": {
    "XOM": { "shares": 50, "avg_cost": 118.32 }
  },
  "last_updated": "2026-10-13T18:04:00Z"
}
```

`agent` is one of `technical_trader`, `fundamental_trader`,
`retail_investor`. `portfolio.py init <agent> <starting_cash>` creates
this file if missing (no-op with a message if it already exists, so
re-running setup is safe).

### `data/trades/{agent}.jsonl`

One JSON object per line, append-only:

```json
{"timestamp": "2026-10-13T18:04:00Z", "round_id": "2026-10-13-oilgas-01", "agent": "technical_trader", "ticker": "XOM", "action": "buy", "qty": 50, "price": 118.32, "status": "executed", "cash_after": 44084.00, "rationale": "RSI14 28, oversold bounce off 50d SMA"}
```

Rejected orders are logged the same way with `"status": "rejected"` and
a `"reason"` field instead of `cash_after`, so the audit trail includes
judgment errors (e.g. an agent trying to oversize a position), which the
reviewer can comment on.

### `data/performance/log.md`

Append-only. One `##` section per review, one `###` subsection per
agent, containing a small metrics table (starting cash, current value,
realized/unrealized return %, benchmark return %) followed by narrative
rationale.

## Scripts

Deterministic Python CLI tools under `scripts/`, called by agents via
Bash. These own all arithmetic and all external data access — agents
never compute portfolio math or fetch raw data themselves.

### `scripts/portfolio.py`

- `init <agent> <starting_cash>` — create portfolio file if missing.
- `show <agent>` — print current portfolio JSON.
- `trade <agent> <ticker> <buy|sell> --round-id ID --rationale TEXT` plus
  exactly one sizing flag: `--shares N`, `--cash-amount X`, or
  `--pct-cash P`. For `--cash-amount`/`--pct-cash`, the script itself
  fetches the current price and converts to a whole share count
  (rounded down), so position sizing is still deterministic math, never
  something an agent computes by hand. Validates (cash ≥ cost for buy;
  shares held ≥ qty for sell; resulting qty > 0), executes and updates
  the ledger (averaging cost basis on repeated buys) and appends to the
  trade log, or rejects and appends a rejection log entry. Prints the
  resulting state (or rejection reason) as JSON.
- `history <agent> [--since TIMESTAMP]` — print trade log entries, for
  reviewer use.

### `scripts/market_data.py`

Backed by `yfinance`; no API key required.

- `quote <ticker>` — current/last price.
- `history <ticker> --period --interval` — OHLCV as JSON.
- `indicators <ticker>` — computed RSI(14), MACD, SMA(20/50/200), and
  recent volume vs. 20-day average, so the Technical Trader works from
  precomputed numbers rather than doing math itself.
- `fundamentals <ticker>` — P/E, PEG, revenue growth, margins,
  debt/equity, market cap, sector, analyst target (from yfinance
  `.info`).
- `news <ticker>` — recent ticker-specific headlines (yfinance `.news`),
  as a supplement to the Retail Investor's broader WebSearch use.

## Error Handling

- `portfolio.py trade` rejects invalid orders outright (insufficient
  cash, insufficient shares, unknown ticker, non-positive qty) rather
  than partially applying them. The rejection is logged and surfaced to
  the user via the boss's round summary.
- Data fetch failures (network issue, bad ticker, delisted symbol)
  surface as a clear error from the script; a trader agent that can't
  get data for a given ticker holds/skips it and says so, rather than
  guessing values.
- A single trader agent erroring out, or a single ticker failing to
  fetch, does not abort the whole round — the boss continues with
  whatever succeeded and reports the gap in its summary.
- The reviewer handles rounds with zero executed trades (all holds)
  gracefully, logging "no action taken" rather than erroring on empty
  data.

## Testing Strategy

- `scripts/portfolio.py` is money-correctness-critical and gets a pytest
  suite: buy/sell happy paths, insufficient-cash rejection,
  insufficient-shares-to-sell rejection, repeated buys averaging cost
  basis correctly, zero/negative quantity guards, idempotent `init`.
- `scripts/market_data.py` gets a lighter test with mocked yfinance
  responses to verify parsing and indicator math (RSI/MACD/SMA formulas
  against known values), since live network calls aren't suitable for
  automated tests.
- End-to-end validation is manual: run one real round on a small test
  universe (e.g. 3 tickers), confirm all three portfolios update
  correctly and logs are legible, then run a review and confirm the
  output reads sensibly, before treating the system as done.

## Decisions Log

Captured from brainstorming, for future reference:

- **Purpose**: paper trading simulation — virtual portfolios against
  real market data, no real broker.
- **Data sources**: free, no API keys — yfinance for prices/fundamentals,
  WebSearch for news/macro/sentiment.
- **Runtime**: Claude Code project-level subagents
  (`.claude/agents/*.md`), not a standalone always-running app. Python
  scripts exist only as deterministic tools the agents invoke via Bash.
- **Stock universe**: not fixed in the system — the user supplies it per
  round (explicit tickers or a sector/theme the boss resolves).
- **Starting capital**: $50,000 per trader agent, equal across all
  three, for comparability.
- **Trade execution**: centralized in `portfolio.py`, invoked by the
  boss — trader agents decide, they do not touch the ledger directly.
- **Review cadence**: on-demand only, triggered explicitly by the user —
  not automatic after every trading round.
