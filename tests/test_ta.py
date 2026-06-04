"""ta.py — ATR / ADX 数值正确性与样本不足处理。"""
from collections import namedtuple

from common.ta import adx, atr, sma

K = namedtuple("Kline", "ts open high low close volume")


def _k(o, h, l, c):
    return K(0, o, h, l, c, 1.0)


def test_sma_basic_and_short():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1], 2) is None


def test_atr_constant_range():
    # 每根 H-L=2，且无跳空 → ATR 收敛到 2
    ks = [_k(100, 101, 99, 100) for _ in range(30)]
    a = atr(ks, 14)
    assert a is not None
    assert abs(a - 2.0) < 1e-9


def test_atr_insufficient():
    ks = [_k(100, 101, 99, 100) for _ in range(5)]
    assert atr(ks, 14) is None


def test_adx_strong_uptrend():
    # 每根整体抬升 1：+DM>0, -DM=0 → +DI 主导, ADX 趋近高位
    ks = [_k(100 + i, 101 + i, 99 + i, 100 + i) for i in range(40)]
    res = adx(ks, 14)
    assert res is not None
    adx_val, pdi, mdi = res
    assert pdi > mdi
    assert adx_val > 30          # 强趋势


def test_adx_flat_no_trend():
    ks = [_k(100, 101, 99, 100) for _ in range(40)]
    res = adx(ks, 14)
    assert res is not None
    adx_val, _, _ = res
    assert adx_val < 18          # 无趋势


def test_adx_insufficient():
    ks = [_k(100, 101, 99, 100) for _ in range(10)]
    assert adx(ks, 14) is None
