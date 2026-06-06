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
  rsi: {period: 14, overbought: 70, oversold: 30}
  liquidation: {crowded_long_ratio: 1.5, crowded_short_ratio: 0.67,
                crowded_account_ratio: 0.62}
  long_short: {bullish_ratio: 1.1, bearish_ratio: 0.91,
               strong_bullish_ratio: 1.25, strong_bearish_ratio: 0.8,
               account_bias_ratio: 0.54, strong_account_bias_ratio: 0.58,
               extreme_long_ratio: 1.5, extreme_short_ratio: 0.67,
               extreme_account_ratio: 0.62}
  onchain: {netflow_btc_threshold: 100, netflow_btc_strong: 500}
  vol_regime: {atr_period: 14, high_atr_pct: 1.2, low_atr_pct: 0.25}
fusion:
  base_weights: {structure: 1.5, volume: 2.0, adx: 0.5, fib: 0.8,
                 candle: 1.0, macd: 1.0, rsi: 0.8, wyckoff: 1.2,
                 oi_funding: 1.0, basis: 0.8, liquidation: 0.8,
                 long_short: 0.4, onchain: 0.7, macro: 0.6, vol_regime: 0.4}
  trend_multiplier: {with_trend: 1.5, against_trend: 0.5}
  data_quality_multiplier: {exact: 1.0, approximated: 0.7, stale: 0.3, unavailable: 0.0}
  trend_multiplier_exempt: [wyckoff]
  exempt_events: [UTAD, SOW, Spring, SC]
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
