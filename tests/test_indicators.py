import pytest

import indicators


def test_sma_basic():
    assert indicators.sma([1, 2, 3, 4, 5], 3) == pytest.approx(4.0)


def test_sma_insufficient_values_raises():
    with pytest.raises(ValueError):
        indicators.sma([1, 2], 3)


def test_ema_series_of_constant_values_is_constant():
    values = [10.0] * 40
    result = indicators.ema_series(values, span=12)
    assert result[-1] == pytest.approx(10.0)
    assert all(v == pytest.approx(10.0) for v in result)


def test_rsi_hand_computed_mixed_gains_and_losses():
    # 10 up-days of +2, then 4 down-days of -1, period=14
    prices = [50, 52, 54, 56, 58, 60, 62, 64, 66, 68, 70, 69, 68, 67, 66]
    result = indicators.rsi(prices, period=14)
    # avg_gain = 20/14, avg_loss = 4/14, rs = 5.0, rsi = 100 - 100/6
    assert result == pytest.approx(83.33333333333333)


def test_rsi_all_gains_is_100():
    prices = list(range(100, 115))  # 15 values, 14 pure gains
    assert indicators.rsi(prices, period=14) == pytest.approx(100.0)


def test_rsi_insufficient_values_raises():
    with pytest.raises(ValueError):
        indicators.rsi([1, 2, 3], period=14)


def test_macd_of_constant_series_is_zero():
    values = [10.0] * 40
    result = indicators.macd(values)
    assert result["macd"] == pytest.approx(0.0)
    assert result["signal"] == pytest.approx(0.0)
    assert result["histogram"] == pytest.approx(0.0)


def test_macd_of_uptrend_is_positive():
    values = [float(v) for v in range(1, 41)]
    result = indicators.macd(values)
    assert result["macd"] > 0


def test_macd_insufficient_values_raises():
    with pytest.raises(ValueError):
        indicators.macd([1.0] * 10)


def test_volume_trend_hand_computed():
    volumes = [100] * 20 + [150]
    assert indicators.volume_trend(volumes, window=20) == pytest.approx(1.5)


def test_volume_trend_zero_baseline_raises():
    volumes = [0] * 20 + [50]
    with pytest.raises(ValueError):
        indicators.volume_trend(volumes, window=20)


def test_volume_trend_insufficient_values_raises():
    with pytest.raises(ValueError):
        indicators.volume_trend([100] * 5, window=20)
