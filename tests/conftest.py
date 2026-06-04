"""检测层测试共享 fixture：造 K 线、假快照、检测用 config。"""
import textwrap
from collections import namedtuple

import pytest

from common.config import load_config

K = namedtuple("Kline", "ts open high low close volume")

_DET_CFG = """
meta: {label: t, symbol: BTC-USDT-SWAP}
timeframes: {all: ["15m"], primary: "15m", higher: [], min_klines: 300}
scoring: {push_threshold: 65, standard_card_score: 60, conflict_score_cap: 55}
plan_builder: {entry_max_deviation_pct: 2.0, stop_min_pct: 0.5, stop_max_pct: 5.0,
               min_risk_reward: 1.5, atr_period: 14, signal_ttl_klines: 4}
hard_constraints: {contextual_veto: {adx_min: 18}}
detectors:
  structure: {swing_lookback: 5, swing_confirm_delay: 2}
  volume: {spike_ratio: 2.0, breakout_min_ratio: 1.2}
  adx: {period: 14, strong: 30}
  fib: {levels: [0.382, 0.5, 0.618, 0.786], extensions: [1.272, 1.618],
        confluence_tolerance_pct: 0.5}
display: {timezone: UTC}
ops: {db_path: data/t.db}
"""


@pytest.fixture
def dcfg(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent(_DET_CFG), encoding="utf-8")
    return load_config(p)


@pytest.fixture
def make_klines():
    """rows: [(open,high,low,close,volume), ...] → [Kline...]，ts 自动递增。"""
    def _make(rows, start_ts=1_700_000_000, step=900):
        return [K(start_ts + i * step, *r) for i, r in enumerate(rows)]
    return _make


class _FakeSnap:
    def __init__(self, mapping, sources=None, data_quality=None):
        self._m = mapping
        self.sources = sources or {}
        self.data_quality = data_quality or {}

    def klines(self, tf):
        return self._m.get(tf, [])

    def last_close(self, tf):
        ks = self._m.get(tf, [])
        return ks[-1].close if ks else None


@pytest.fixture
def make_snap():
    def _make(sources=None, data_quality=None, **tf_klines):
        return _FakeSnap(tf_klines, sources, data_quality)
    return _make
