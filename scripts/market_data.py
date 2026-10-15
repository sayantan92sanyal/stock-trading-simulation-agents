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
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        raise ValueError(f"no price data available for {ticker!r}")
    return float(hist["Close"].iloc[-1])


def get_history(ticker, period="6mo", interval="1d"):
    tk = yf.Ticker(ticker)
    hist = tk.history(period=period, interval=interval)
    if hist.empty:
        raise ValueError(f"no price data available for {ticker!r}")
    hist = hist.dropna(subset=["Close"])
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
