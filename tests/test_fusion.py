"""fusion.py — 加权评分、硬约束/veto、冲突、多周期封顶（架构四节 / D5 / 缺口9）。"""
import textwrap

import pytest

from common.config import load_config
from fusion.fusion import fuse

_CFG = """
meta: {label: t, symbol: BTC-USDT-SWAP}
timeframes: {all: ["15m","4h","1d"], primary: "15m", higher: ["4h","1d"], min_klines: 300}
scoring: {push_threshold: 65, standard_card_score: 60, conflict_score_cap: 55}
plan_builder: {stop_min_pct: 0.5, stop_max_pct: 5.0, min_risk_reward: 1.5}
hard_constraints:
  structural_veto: {higher_tf_opposite: true, breakout_low_volume: true}
  contextual_veto: {adx_min: 18}
fusion:
  base_weights: {structure: 1.5, volume: 2.0, adx: 0.5, fib: 0.8}
  trend_multiplier: {with_trend: 1.5, against_trend: 0.5}
  data_quality_multiplier: {exact: 1.0, approximated: 0.7, stale: 0.3, unavailable: 0.0}
  trend_multiplier_exempt: [wyckoff]
  exempt_events: [UTAD, SOW, Spring, SC]
display: {timezone: UTC}
ops: {db_path: data/t.db}
"""


@pytest.fixture
def fcfg(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent(_CFG), encoding="utf-8")
    return load_config(p)


def _sig(direction, strength, events=None, details=None):
    return {"direction": direction, "strength": strength,
            "events": events or [], "details": details or {}}


def _adx(val):
    return _sig("neutral", 3, details={"adx": val})


def test_all_bullish_aligned_high_score(fcfg):
    signals = {"structure": _sig("bullish", 4), "volume": _sig("bullish", 4),
               "adx": _adx(25), "fib": _sig("neutral", 2)}
    r = fuse(signals, fcfg, htf_directions={"4h": "bullish", "1d": "bullish"})
    assert r.direction == "bullish"
    assert r.score >= 60
    assert r.recommendation == "signal"
    assert not r.vetoed
    assert r.radar["adx"] == 3                 # 无向检测器仍入雷达
    assert "structure" in r.weight_breakdown


def test_structural_veto_higher_tf_opposite(fcfg):
    signals = {"structure": _sig("bullish", 4), "volume": _sig("bullish", 4),
               "adx": _adx(25)}
    r = fuse(signals, fcfg, htf_directions={"4h": "bearish", "1d": "bearish"})
    assert r.vetoed
    assert any("大周期" in x for x in r.veto_reasons)
    assert r.recommendation == "wait"
    assert r.hard_constraints["trend_aligned"] is False


def test_structural_veto_breakout_low_volume(fcfg):
    signals = {
        "structure": _sig("bullish", 4, events=["breakout_up"]),
        "volume": _sig("bullish", 3, details={"breakout_volume_ok": False}),
        "adx": _adx(25),
    }
    r = fuse(signals, fcfg)                     # 无 htf → dominant neutral
    assert r.vetoed
    assert any("缩量" in x for x in r.veto_reasons)


def test_contextual_veto_low_adx(fcfg):
    signals = {"structure": _sig("bullish", 4), "volume": _sig("bullish", 4),
               "adx": _adx(10)}                 # ADX < 18
    r = fuse(signals, fcfg)
    assert r.vetoed
    assert any("ADX" in x for x in r.veto_reasons)
    assert r.hard_constraints["adx_sufficient"] is False


def test_long_short_conflict_recorded(fcfg):
    signals = {"structure": _sig("bullish", 4), "volume": _sig("bearish", 4),
               "adx": _adx(25)}
    r = fuse(signals, fcfg)
    assert any("多空分歧" in c for c in r.conflicts)


def test_multi_timeframe_conflict_caps_score(fcfg):
    signals = {"structure": _sig("bullish", 5), "volume": _sig("bullish", 5),
               "adx": _adx(40)}
    r = fuse(signals, fcfg, htf_directions={"4h": "bullish", "1d": "bearish"})
    assert r.timeframe_alignment["conflict"] is True
    assert r.score <= 55                        # 封顶 conflict_score_cap


def test_no_directional_signal_is_wait(fcfg):
    signals = {"adx": _adx(25), "fib": _sig("neutral", 2)}
    r = fuse(signals, fcfg)
    assert r.direction == "neutral"
    assert r.score == 0
    assert r.recommendation == "wait"
