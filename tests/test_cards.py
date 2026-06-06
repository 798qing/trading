"""card_builder.py — 快报/观望卡/信号卡渲染（规格 specs/card_layout.md）。"""
from types import SimpleNamespace

from fusion.fusion import FusionResult
from output import card_builder as cb
from plan.plan_builder import TradePlan
from review.risk import RiskResult


def _analysis(make_klines, make_snap, *, fusion, plan, recommendation, reasons=None,
              risk=None):
    snap = make_snap(sources={"mark": {"price": 100.0},
                              "funding": {"rate": 0.0001}, "oi": {"oi": 12345.0}},
                     data_quality={"is_complete": True, "has_stale_source": False},
                     **{"15m": make_klines([(100, 101, 99, 100, 1)] * 20)})
    return SimpleNamespace(snapshot=snap, fusion=fusion, plan=plan,
                           recommendation=recommendation, reasons=reasons or [],
                           risk=risk or RiskResult(False))


def _signal_fusion():
    return FusionResult(
        score=72, direction="bullish", recommendation="signal", vetoed=False,
        hard_constraints={"trend_aligned": True, "volume_confirmed": True,
                          "adx_sufficient": True, "no_macro_event": True},
        radar={"structure": 4, "volume": 4, "adx": 3, "fib": 2})


def _valid_plan():
    return TradePlan("long", True, entry_zone=[99.0, 100.0], stop_loss=97.0,
                     targets=[104.0, 107.0], invalid_if="15m 收盘跌破 97.0",
                     risk_reward=1.8,
                     source_levels={"entry": ["fib_ret"], "stop": ["swing_low", "ATR"],
                                    "target": ["swing_high", "fib_ext/swing"]},
                     key_levels={"resistances": [[104.0, "swing_high"]],
                                 "supports": [[97.0, "swing_low"]]})


def test_signal_card_has_plan_and_no_llm(dcfg, make_klines, make_snap):
    a = _analysis(make_klines, make_snap, fusion=_signal_fusion(), plan=_valid_plan(),
                  recommendation="signal",
                  risk=RiskResult(False, warnings=["入场上方阻力较近，目标空间有限"]))
    card = cb.render(a, dcfg)
    assert "BTC" in card and "信号" in card
    assert "交易计划" in card
    assert "99.0" in card and "97.0" in card and "104.0" in card   # 价格上卡
    assert "盈亏比" in card and "1.8" in card
    assert "纯检测器" in card                                       # 阶段1无 LLM 标注
    assert "fib_ret" in card                                       # source_levels 可追溯
    assert "阻力较近" in card                                      # 风险提示


def test_signal_card_can_include_llm_block(dcfg, make_klines, make_snap):
    a = _analysis(make_klines, make_snap, fusion=_signal_fusion(), plan=_valid_plan(),
                  recommendation="signal")
    a.llm_output = {
        "status": "ok",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "prompt_version": "full_analysis_v1",
        "text": "综合判断：只引用既有交易计划，谨慎看多。",
    }
    card = cb.render(a, dcfg)
    assert "LLM 综合解读（deepseek）" in card
    assert "谨慎看多" in card


def test_wait_card_lists_reasons_and_levels(dcfg, make_klines, make_snap):
    fusion = FusionResult(score=53, direction="bearish", recommendation="wait",
                          vetoed=False, radar={"structure": 4, "volume": 2})
    plan = TradePlan("none", False,
                     key_levels={"resistances": [[105.0, "swing_high"]],
                                 "supports": [[95.0, "fib_ret"]]})
    a = _analysis(make_klines, make_snap, fusion=fusion, plan=plan,
                  recommendation="wait", reasons=["综合评分不足（53<60）"])
    card = cb.render(a, dcfg)
    assert "观望" in card
    assert "为什么不动" in card and "综合评分不足" in card
    assert "105.0" in card and "95.0" in card        # 关键位
    assert "跌破" in card                            # bearish lean → 等什么


def test_quick_card_is_compact(dcfg, make_klines, make_snap):
    a = _analysis(make_klines, make_snap, fusion=_signal_fusion(), plan=_valid_plan(),
                  recommendation="signal")
    card = cb.render(a, dcfg, quick=True)
    assert "快报" in card
    assert "入场" in card and "止损" in card
    assert card.count("\n") <= 5                     # 极简单行密排


def test_quick_card_hides_wait_sample_plan(dcfg, make_klines, make_snap):
    fusion = FusionResult(score=48, direction="bearish", recommendation="wait",
                          vetoed=False, radar={"structure": 4, "volume": 2})
    plan = TradePlan("short", True, entry_zone=[101.0, 102.0], stop_loss=104.0,
                     targets=[98.0, 96.0],
                     key_levels={"resistances": [[102.0, "swing_high"]],
                                 "supports": [[98.0, "swing_low"]]})
    a = _analysis(make_klines, make_snap, fusion=fusion, plan=plan,
                  recommendation="wait", reasons=["综合评分不足"])
    card = cb.render(a, dcfg, quick=True)
    assert "快报" in card
    assert "入场" not in card and "止损" not in card


def test_render_picks_wait_when_plan_invalid(dcfg, make_klines, make_snap):
    # recommendation=signal 但 plan 无效 → 仍走观望卡（防止出空计划卡）
    a = _analysis(make_klines, make_snap, fusion=_signal_fusion(),
                  plan=TradePlan("none", False, key_levels={"resistances": [],
                                                            "supports": []}),
                  recommendation="signal")
    card = cb.render(a, dcfg)
    assert "观望" in card
