"""wyckoff 候选检测器（D4：只观察、不评分、不推送）。"""
from types import SimpleNamespace

from detectors.wyckoff import WyckoffDetector
from fusion.fusion import fuse
from output import card_builder as cb
from plan.plan_builder import TradePlan
from review.risk import RiskResult


def _zigzag(pivots, bars=7):
    rows = []
    for a, b in zip(pivots, pivots[1:]):
        for j in range(bars):
            p = a + (b - a) * j / bars
            rows.append((p, p + 0.5, p - 0.5, p, 1000.0))
    return rows


def test_spring_candidate_is_neutral_and_observation(dcfg, make_klines, make_snap):
    # 先形成 swing 低，再用末根跌破后收回 → spring 候选
    rows = _zigzag([110, 100, 108, 102])
    rows += [(102, 103, 98, 101, 1000.0)]      # 末根：插破前低后收回
    r = WyckoffDetector().detect(make_snap(**{"15m": make_klines(rows)}), dcfg)
    assert r.direction == "neutral"            # D4：永不给方向
    assert r.details["needs_confirmation"] is True
    # 若识别出 spring，应为 candidate 且带失效条件
    if r.events:
        assert any("candidate" in e for e in r.events)


def test_wyckoff_neutral_excluded_from_scoring(dcfg):
    # wyckoff 即便强度不低，neutral 也不进 fusion 评分
    signals = {
        "structure": {"direction": "bullish", "strength": 4, "events": [], "details": {}},
        "wyckoff": {"direction": "neutral", "strength": 5,
                    "events": ["spring_candidate"], "details": {}},
    }
    r = fuse(signals, dcfg)
    assert "wyckoff" in r.radar                 # 进雷达
    assert "wyckoff" not in r.weight_breakdown   # 不进加权评分（D4）


def test_wait_card_shows_wyckoff_observation(dcfg, make_klines, make_snap):
    snap = make_snap(sources={"mark": {"price": 100.0}},
                     **{"15m": make_klines([(100, 101, 99, 100, 1)] * 5)})
    from fusion.fusion import FusionResult
    a = SimpleNamespace(
        snapshot=snap, recommendation="wait", reasons=["评分不足"],
        risk=RiskResult(False),
        fusion=FusionResult(score=40, direction="neutral", recommendation="wait",
                            vetoed=False, radar={"structure": 3}),
        plan=TradePlan("none", False, key_levels={"resistances": [[105.0, "swing_high"]],
                                                  "supports": [[95.0, "fib_ret"]]}),
        signals={"wyckoff": {"direction": "neutral", "strength": 2,
                             "events": ["spring_candidate"],
                             "details": {"phase_hypothesis": "accumulation",
                                         "invalid_if": "下一根 15m 收盘跌破 95"}}},
    )
    card = cb.render(a, dcfg)
    assert "观察字段" in card and "威科夫" in card
    assert "spring_candidate" in card and "未确认" in card
