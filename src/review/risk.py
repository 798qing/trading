"""风控复核（架构六节）——**只降级，不升级**。

输入：plan_builder 输出 + fusion + snapshot。输出降级决定、风险提示、离散仓位建议。
仓位建议只能是离散、保守措辞（如"建议仓位减半"），绝不给精确下注比例（D1/D11 边界）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RiskResult:
    downgrade: bool
    reasons: list[str] = field(default_factory=list)   # 触发降级的原因
    warnings: list[str] = field(default_factory=list)  # 风险提示（不降级）
    position_advice: str | None = None                 # 离散保守措辞


# 资金费率“偏高”阈值（每 8h），多头拥挤提示用
_FUNDING_HIGH = 0.0005


def review_risk(plan, fusion, snapshot, cfg) -> RiskResult:
    if not plan.valid or plan.direction not in ("long", "short"):
        return RiskResult(False, ["无可执行计划"], [], None)

    reasons: list[str] = []
    warnings: list[str] = []

    funding = (snapshot.sources.get("funding") or {}).get("rate")
    dq = getattr(snapshot, "data_quality", None) or {}

    # 负费率做空 → 降级（架构六节）
    if funding is not None and plan.direction == "short" and funding < 0:
        reasons.append(f"负资金费率（{funding:+.4%}）做空 → 降级")
    # 费率偏高 + 做多 → 多头拥挤提示（不降级）
    if funding is not None and plan.direction == "long" and funding > _FUNDING_HIGH:
        warnings.append(f"资金费率偏高（{funding:+.4%}），多头拥挤")

    # 接近反向关键位入场 → 风险提示（不降级）
    res = plan.key_levels.get("resistances", [])
    sup = plan.key_levels.get("supports", [])
    risk_room = _risk_room(plan)
    if plan.direction == "long" and res and risk_room:
        gap = res[0][0] - plan.entry_zone[1]
        if 0 < gap < risk_room:
            warnings.append("入场上方阻力较近，目标空间有限")
    if plan.direction == "short" and sup and risk_room:
        gap = plan.entry_zone[0] - sup[0][0]
        if 0 < gap < risk_room:
            warnings.append("入场下方支撑较近，目标空间有限")

    # 数据质量降级 → 离散仓位建议（保守措辞）
    position_advice = None
    if not dq.get("is_complete", True):
        position_advice = "建议观望或仓位减半（数据不完整）"
    elif dq.get("has_stale_source", False):
        position_advice = "建议仓位减半（部分数据源过期）"

    return RiskResult(downgrade=bool(reasons), reasons=reasons, warnings=warnings,
                      position_advice=position_advice)


def _risk_room(plan) -> float | None:
    """入场到止损的距离（风险），用于判断目标空间是否过窄。"""
    if not plan.entry_zone or plan.stop_loss is None:
        return None
    if plan.direction == "long":
        return plan.entry_zone[0] - plan.stop_loss
    return plan.stop_loss - plan.entry_zone[1]


def decide(fusion, validation, risk) -> tuple[str, list[str]]:
    """综合 fusion/validate/risk 给最终建议。**只会降级，不会升级。**

    返回 (recommendation, reasons)。recommendation ∈ {"signal","wait"}。
    """
    if fusion.recommendation == "wait":
        return "wait", (fusion.veto_reasons or ["评分不足或无信号"])
    if not validation.ok:
        return "wait", validation.reasons          # 数值校验不过 → 强制 wait
    if risk.downgrade:
        return "wait", risk.reasons                # 风控降级 → wait
    return "signal", []
