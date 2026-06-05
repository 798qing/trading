"""find_swings — 防前视可见性（P0-3）。"""
from collections import namedtuple

from detectors.base import find_swings

K = namedtuple("Kline", "ts open high low close volume")


def _series_with_peak_at(idx, n=21):
    rows = [K(i, 100, 101, 99, 100, 1) for i in range(n)]
    p = rows[idx]
    rows[idx] = K(p.ts, 100, 120, 99, 100, 1)   # 在 idx 处插一个明显高点
    return rows


def test_swing_visible_only_after_confirm_delay():
    ks = _series_with_peak_at(10, n=21)          # 末尾索引 20
    highs, _ = find_swings(ks, lookback=2, confirm_delay=3)
    assert any(s.idx == 10 for s in highs)        # 后方有足够 K 线 → 可见


def test_swing_hidden_before_confirm():
    ks = _series_with_peak_at(10, n=21)
    # 截到索引 12（需 10+max(2,3)=13 才可见）→ 不可见
    highs, _ = find_swings(ks[:13], lookback=2, confirm_delay=3)
    assert all(s.idx != 10 for s in highs)


def test_flat_plateau_yields_no_false_swings():
    # 审查#1 回归：完全平坦序列不得把每根都误标为 swing（严格分形）
    ks = [K(i, 100, 101, 99, 100, 1) for i in range(21)]
    highs, lows = find_swings(ks, lookback=2, confirm_delay=2)
    assert highs == [] and lows == []


def test_adjacent_equal_highs_not_both_swings():
    # 两个相邻等高点：严格不等号下都不算 swing（不再误标）
    ks = [K(i, 100, 101, 99, 100, 1) for i in range(21)]
    ks[9] = K(9, 100, 120, 99, 100, 1)
    ks[10] = K(10, 100, 120, 99, 100, 1)   # 与 idx9 等高
    highs, _ = find_swings(ks, lookback=2, confirm_delay=2)
    assert all(s.idx not in (9, 10) for s in highs)


def test_empty_when_too_short():
    ks = [K(i, 100, 101, 99, 100, 1) for i in range(4)]
    highs, lows = find_swings(ks, lookback=5, confirm_delay=2)
    assert highs == [] and lows == []
