"""Pure, deterministic technical indicator calculations. No I/O, no network."""


def sma(values, window):
    if len(values) < window:
        raise ValueError(f"need at least {window} values, got {len(values)}")
    return sum(values[-window:]) / window


def ema_series(values, span):
    if not values:
        raise ValueError("values must not be empty")
    alpha = 2 / (span + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        raise ValueError(f"need at least {period + 1} values, got {len(values)}")
    window = values[-(period + 1):]
    gains = []
    losses = []
    for prev, curr in zip(window[:-1], window[1:]):
        change = curr - prev
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-change)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal:
        raise ValueError(f"need at least {slow + signal} values, got {len(values)}")
    fast_ema = ema_series(values, fast)
    slow_ema = ema_series(values, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = ema_series(macd_line, signal)
    return {
        "macd": macd_line[-1],
        "signal": signal_line[-1],
        "histogram": macd_line[-1] - signal_line[-1],
    }


def volume_trend(volumes, window=20):
    if len(volumes) < window + 1:
        raise ValueError(f"need at least {window + 1} values, got {len(volumes)}")
    baseline = sum(volumes[-(window + 1):-1]) / window
    if baseline == 0:
        raise ValueError("baseline average volume is zero")
    return volumes[-1] / baseline
