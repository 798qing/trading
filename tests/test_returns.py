"""returns.py — 对数收益率底座（D10）。"""
import math

import pytest

from common import returns


def test_log_return_basic():
    assert returns.log_return(100, 110) == pytest.approx(math.log(1.1))
    assert returns.log_return(100, 100) == 0.0


def test_log_return_rejects_nonpositive():
    with pytest.raises(ValueError):
        returns.log_return(0, 100)
    with pytest.raises(ValueError):
        returns.log_return(100, -1)


def test_log_returns_length_and_additivity():
    prices = [100, 110, 99, 105]
    rets = returns.log_returns(prices)
    assert len(rets) == len(prices) - 1
    # 对数收益率可加：累计 == 直接首尾对数收益
    assert sum(rets) == pytest.approx(returns.log_return(prices[0], prices[-1]))


def test_cumulative_return_simple_pct():
    # +10% 再 -10%（对数）→ 简单收益略小于 0
    rets = returns.log_returns([100, 110, 99])
    assert returns.cumulative_return(rets) == pytest.approx(99 / 100 - 1)


def test_stdev_short_series_zero():
    assert returns.stdev([]) == 0.0
    assert returns.stdev([0.1]) == 0.0
