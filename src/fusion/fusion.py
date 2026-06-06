"""信号聚合层（架构四节）。

不做简单多空投票，而是：加权综合分 + 雷达图 + 硬约束 + 冲突 + weight_breakdown。

硬约束两类（D5）：
  structural_veto（无例外）：大周期方向相反 / 突破缩量
  contextual_veto（有例外）：ADX<min（wyckoff 确认事件豁免，阶段1无）/ 宏观事件窗口

评分：每个有方向的检测器贡献 base_weight × strength × trend_mult × dq_mult（带符号）。
net 决定方向，|net|/max_possible 决定分数（全员强信号且顺势 → 100）。
多周期冲突（缺口9）→ 评分封顶 conflict_score_cap。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_SIGN = {"bullish": 1, "bearish": -1, "neutral": 0}


@dataclass
class FusionResult:
    score: int
    direction: str                       # 候选方向（信息性，veto 后仍保留以填“等什么”）
    recommendation: str                  # "signal" | "wait"
    vetoed: bool
    veto_reasons: list[str] = field(default_factory=list)
    hard_constraints: dict[str, bool] = field(default_factory=dict)
    radar: dict[str, int] = field(default_factory=dict)
    subscores: dict[str, Any] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    weight_breakdown: dict[str, dict] = field(default_factory=dict)
    timeframe_alignment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score, "direction": self.direction,
            "recommendation": self.recommendation, "vetoed": self.vetoed,
            "veto_reasons": self.veto_reasons,
            "hard_constraints": self.hard_constraints, "radar": self.radar,
            "subscores": self.subscores, "conflicts": self.conflicts,
            "weight_breakdown": self.weight_breakdown,
            "timeframe_alignment": self.timeframe_alignment,
        }


def _dominant_htf(htf: dict[str, str], higher_order: list[str]) -> tuple[str, bool]:
    """返回 (dominant_direction, conflict)。

    高低周期不一致 → conflict=True，dominant 取最高级别周期（design：以高周期为主）。
    """
    dirs = [htf.get(tf, "neutral") for tf in higher_order if tf in htf]
    non_neutral = [d for d in dirs if d != "neutral"]
    if not non_neutral:
        return "neutral", False
    conflict = ("bullish" in non_neutral and "bearish" in non_neutral)
    # 最高级别周期（higher_order 末位）方向优先
    dominant = "neutral"
    for tf in reversed(higher_order):
        if htf.get(tf, "neutral") != "neutral":
            dominant = htf[tf]
            break
    return dominant, conflict


def fuse(signals: dict[str, dict], cfg, htf_directions: dict[str, str] | None = None,
         data_quality: dict | None = None) -> FusionResult:
    """signals: {module: DetectorResult.to_dict()}（primary 周期）。"""
    fcfg = cfg.get("fusion", {})
    base_w: dict[str, float] = fcfg.get("base_weights", {})
    tm = fcfg.get("trend_multiplier", {"with_trend": 1.5, "against_trend": 0.5})
    with_trend = tm.get("with_trend", 1.5)
    against_trend = tm.get("against_trend", 0.5)
    dq_mult_map = fcfg.get("data_quality_multiplier",
                           {"exact": 1.0, "approximated": 0.7, "stale": 0.3,
                            "unavailable": 0.0})
    exempt_modules = set(fcfg.get("trend_multiplier_exempt", []))
    exempt_events = set(fcfg.get("exempt_events", []))

    higher_order: list[str] = cfg.get("timeframes.higher", [])
    htf = htf_directions or {}
    dominant, htf_conflict = _dominant_htf(htf, higher_order)

    radar: dict[str, int] = {}
    breakdown: dict[str, dict] = {}
    net = 0.0
    max_possible = 0.0
    dir_counts = {"bullish": [], "bearish": []}

    for module, w in base_w.items():
        sig = signals.get(module)
        if not sig:
            continue
        direction = sig.get("direction", "neutral")
        strength = int(sig.get("strength", 1))
        radar[module] = strength
        sign = _SIGN.get(direction, 0)
        if sign == 0:
            continue   # 无方向检测器（adx/部分fib）不进方向评分，只入雷达/硬约束

        # trend_multiplier（反转模块/事件豁免）
        events = set(sig.get("events", []))
        exempt = module in exempt_modules or bool(events & exempt_events)
        if dominant in ("bullish", "bearish") and not exempt:
            if direction == dominant:
                trend_mult = with_trend
            elif _SIGN[direction] == -_SIGN[dominant]:
                trend_mult = against_trend
            else:
                trend_mult = 1.0
        else:
            trend_mult = 1.0

        # data_quality_multiplier（阶段1 OKX 一级数据=exact）
        dq_key = sig.get("details", {}).get("data_quality", "exact")
        dq_mult = dq_mult_map.get(dq_key, 1.0)

        eff = w * trend_mult * dq_mult
        signed = sign * eff * strength
        net += signed
        max_possible += w * with_trend * dq_mult * 5
        dir_counts[direction].append(module)

        breakdown[module] = {
            "base_weight": w, "strength": strength, "trend_mult": trend_mult,
            "dq_mult": dq_mult, "effective_weight": round(eff, 3),
            "signed_contribution": round(signed, 3),
        }

    candidate = "bullish" if net > 0 else "bearish" if net < 0 else "neutral"
    score = int(round(100 * abs(net) / max_possible)) if max_possible > 0 else 0
    score = max(0, min(100, score))

    # 多周期冲突 → 评分封顶（缺口9）
    cap = cfg.get("scoring.conflict_score_cap", 55)
    if htf_conflict and score > cap:
        score = cap

    # --- 硬约束判定 ---
    adx_min = cfg.get("hard_constraints.contextual_veto.adx_min", 18)
    struct = signals.get("structure", {})
    vol = signals.get("volume", {})
    adx_sig = signals.get("adx", {})
    macro_sig = signals.get("macro", {})
    breakout = bool({"breakout_up", "breakdown"} & set(struct.get("events", [])))
    volume_confirmed = (vol.get("details", {}).get("breakout_volume_ok", True)
                        if breakout else True)
    if adx_sig:
        adx_sufficient = adx_sig.get("details", {}).get("adx", 999) >= adx_min
    else:
        adx_sufficient = True
    no_macro_event = macro_sig.get("details", {}).get("no_macro_event", True)
    trend_aligned = (dominant == "neutral" or candidate == "neutral"
                     or candidate == dominant)
    hard_constraints = {
        "trend_aligned": trend_aligned,
        "volume_confirmed": volume_confirmed,
        "adx_sufficient": adx_sufficient,
        "no_macro_event": bool(no_macro_event),
    }

    # --- veto ---
    sv = cfg.get("hard_constraints.structural_veto", {})
    veto_reasons: list[str] = []
    if sv.get("higher_tf_opposite", True) and dominant != "neutral" \
            and candidate != "neutral" and not trend_aligned:
        veto_reasons.append(f"结构性否决：大周期({dominant})与信号({candidate})相反")
    if sv.get("breakout_low_volume", True) and breakout and not volume_confirmed:
        veto_reasons.append("结构性否决：突破缩量")
    if not adx_sufficient:
        veto_reasons.append(f"情境否决：ADX<{adx_min}（无趋势）")
    if not no_macro_event:
        event = macro_sig.get("details", {}).get("event_name") or "宏观事件"
        window = cfg.get("hard_constraints.contextual_veto.macro_event_window_min", 60)
        veto_reasons.append(f"情境否决：{event} 前后 {window}min 宏观窗口")
    vetoed = bool(veto_reasons)

    # --- 冲突 ---
    conflicts: list[str] = []
    if dir_counts["bullish"] and dir_counts["bearish"]:
        conflicts.append(f"多空分歧：看多{dir_counts['bullish']} vs 看空{dir_counts['bearish']}")
    if htf_conflict:
        conflicts.append(f"多周期分歧（评分封顶{cap}）")

    # --- subscores（架构十七节；risk_reward 待 plan_builder 回填）---
    agree = len(dir_counts.get(candidate, [])) if candidate != "neutral" else 0
    total_dir = len(dir_counts["bullish"]) + len(dir_counts["bearish"])
    subscores = {
        "direction_alignment": int(round(100 * agree / total_dir)) if total_dir else 50,
        "structure_quality": int(struct.get("strength", 1)) * 20,
        "entry_location": int(signals.get("fib", {}).get("strength", 1)) * 20,
        "risk_reward": None,              # plan_builder/validate 阶段回填
        "data_quality": _dq_subscore(data_quality),
    }

    recommendation = "signal" if (not vetoed and candidate != "neutral"
                                  and score >= cfg.get("scoring.standard_card_score", 60)
                                  ) else "wait"

    tf_align = {tf: htf.get(tf, "neutral") for tf in higher_order}
    tf_align.update({"conflict": htf_conflict, "dominant": dominant})

    return FusionResult(
        score=score, direction=candidate, recommendation=recommendation,
        vetoed=vetoed, veto_reasons=veto_reasons, hard_constraints=hard_constraints,
        radar=radar, subscores=subscores, conflicts=conflicts,
        weight_breakdown=breakdown, timeframe_alignment=tf_align,
    )


def _dq_subscore(data_quality: dict | None) -> int:
    if not data_quality:
        return 50
    if not data_quality.get("is_complete", True):
        return 40
    if data_quality.get("has_stale_source", False):
        return 70
    return 100
