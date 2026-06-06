"""plan_builder.py — 价格唯一来源（D3）：入场/止损/目标/失效 + source_levels 可追溯。"""
from types import SimpleNamespace

from plan.plan_builder import build_plan


def _fusion(direction, recommendation="signal", score=72, vetoed=False):
    return SimpleNamespace(direction=direction, recommendation=recommendation,
                           score=score, vetoed=vetoed)


def _klines(make_klines, n=30, base=100.0):
    # 平稳箱体，H-L≈1，给 ATR 一个稳定值
    return make_klines([(base, base + 0.5, base - 0.5, base, 1000.0) for _ in range(n)])


def _signals(swing_high, swing_low, events=None):
    return {"structure": {"direction": "bullish", "strength": 4,
                          "events": events or [],
                          "details": {"last_swing_high": swing_high,
                                      "last_swing_low": swing_low}}}


def test_long_plan_prices_ordered_and_traceable(dcfg, make_klines, make_snap):
    snap = make_snap(sources={"mark": {"price": 100.0, "status": "fresh"}},
                     **{"15m": _klines(make_klines)})
    plan = build_plan(_fusion("bullish"), snap, _signals(105.0, 95.0), dcfg)
    assert plan.direction == "long" and plan.valid
    lo, hi = plan.entry_zone
    assert plan.stop_loss < lo <= hi < plan.targets[0] < plan.targets[1]
    assert plan.risk_reward >= dcfg.get("plan_builder.min_risk_reward") - 0.01
    # 每个价格都有来源标签（D3 可追溯）
    assert plan.source_levels["entry"] and plan.source_levels["stop"]
    assert plan.source_levels["target"]
    assert "跌破" in plan.invalid_if


def test_short_plan_mirror(dcfg, make_klines, make_snap):
    snap = make_snap(sources={"mark": {"price": 100.0, "status": "fresh"}},
                     **{"15m": _klines(make_klines)})
    sig = _signals(105.0, 95.0)
    sig["structure"]["direction"] = "bearish"
    plan = build_plan(_fusion("bearish"), snap, sig, dcfg)
    assert plan.direction == "short" and plan.valid
    lo, hi = plan.entry_zone
    assert plan.stop_loss > hi >= lo > plan.targets[0] > plan.targets[1]
    assert "升破" in plan.invalid_if


def test_stop_distance_within_bounds(dcfg, make_klines, make_snap):
    snap = make_snap(sources={"mark": {"price": 100.0, "status": "fresh"}},
                     **{"15m": _klines(make_klines)})
    plan = build_plan(_fusion("bullish"), snap, _signals(105.0, 95.0), dcfg)
    lo = plan.entry_zone[0]
    dist_pct = (lo - plan.stop_loss) / lo * 100
    assert dcfg.get("plan_builder.stop_min_pct") <= dist_pct <= dcfg.get("plan_builder.stop_max_pct")


def test_rr_projection_when_no_resistance(dcfg, make_klines, make_snap):
    # 两个 swing 都在参考价下方 → 无上方阻力 → TP1 按 min_rr 投影
    snap = make_snap(sources={"mark": {"price": 100.0, "status": "fresh"}},
                     **{"15m": _klines(make_klines)})
    plan = build_plan(_fusion("bullish"), snap, _signals(99.0, 95.0), dcfg)
    assert plan.valid
    assert abs(plan.risk_reward - dcfg.get("plan_builder.min_risk_reward")) < 0.1
    assert "rr_projection" in plan.source_levels["target"]   # TP1 来源=按盈亏比投影


def test_wait_returns_key_levels_only(dcfg, make_klines, make_snap):
    snap = make_snap(sources={"mark": {"price": 100.0, "status": "fresh"}},
                     **{"15m": _klines(make_klines)})
    plan = build_plan(_fusion("neutral", recommendation="wait"), snap,
                      _signals(105.0, 95.0), dcfg)
    assert plan.direction == "none" and not plan.valid
    assert plan.entry_zone is None
    assert plan.key_levels["resistances"] or plan.key_levels["supports"]


def test_directional_wait_can_build_backtest_sample_plan(dcfg, make_klines, make_snap):
    snap = make_snap(sources={"mark": {"price": 100.0, "status": "fresh"}},
                     **{"15m": _klines(make_klines)})
    plan = build_plan(_fusion("bearish", recommendation="wait", score=48), snap,
                      _signals(105.0, 95.0), dcfg)
    assert plan.direction == "short" and plan.valid
    assert any("观望采样计划" in note for note in plan.notes)


def test_low_score_wait_keeps_key_levels_only(dcfg, make_klines, make_snap):
    snap = make_snap(sources={"mark": {"price": 100.0, "status": "fresh"}},
                     **{"15m": _klines(make_klines)})
    plan = build_plan(_fusion("bullish", recommendation="wait", score=23), snap,
                      _signals(105.0, 95.0), dcfg)
    assert plan.direction == "none" and not plan.valid
    assert plan.key_levels["resistances"] or plan.key_levels["supports"]


def test_vetoed_wait_keeps_key_levels_only(dcfg, make_klines, make_snap):
    snap = make_snap(sources={"mark": {"price": 100.0, "status": "fresh"}},
                     **{"15m": _klines(make_klines)})
    plan = build_plan(_fusion("bullish", recommendation="wait", score=58, vetoed=True),
                      snap, _signals(105.0, 95.0), dcfg)
    assert plan.direction == "none" and not plan.valid
    assert plan.key_levels["resistances"] or plan.key_levels["supports"]


def test_no_reference_price_fails_gracefully(dcfg, make_klines, make_snap):
    snap = make_snap(**{"15m": []})          # 无 mark、无 K 线
    plan = build_plan(_fusion("bullish"), snap, _signals(105.0, 95.0), dcfg)
    assert plan.direction == "none" and not plan.valid
