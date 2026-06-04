"""数值校验（架构六节）。

校验对象是 plan_builder 的输出（入场区间/止损/目标），不是 LLM 价格（LLM 无权生成价格）。
任一不通过 → ok=False，上层据此强制降级为 wait。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)


def validate_plan(plan, snapshot, cfg) -> ValidationResult:
    pb = cfg.get("plan_builder", {})
    max_dev = pb.get("entry_max_deviation_pct", 2.0) / 100.0
    stop_min = pb.get("stop_min_pct", 0.5) / 100.0
    stop_max = pb.get("stop_max_pct", 5.0) / 100.0
    min_rr = pb.get("min_risk_reward", 1.5)

    # 无可执行计划（观望）本就不需校验，直接判不通过（交由上层走 wait）
    if not plan.valid or plan.direction not in ("long", "short"):
        return ValidationResult(False, ["无可执行计划（观望）"], {})

    reasons: list[str] = []
    checks: dict[str, bool] = {}

    lo, hi = plan.entry_zone
    entry_ref = (lo + hi) / 2
    mark = (snapshot.sources.get("mark") or {}).get("price")

    # 1) 入场偏离标记价
    if mark:
        dev = abs(entry_ref - mark) / mark
        checks["entry_deviation"] = dev <= max_dev
        if dev > max_dev:
            reasons.append(f"入场偏离标记价 {dev*100:.2f}% > {max_dev*100:.1f}%")
    else:
        checks["entry_deviation"] = True   # 无标记价不卡这条

    # 2) 止损距离
    ref_for_stop = lo if plan.direction == "long" else hi
    stop_dist = abs(ref_for_stop - plan.stop_loss) / ref_for_stop
    checks["stop_distance"] = stop_min <= stop_dist <= stop_max
    if not checks["stop_distance"]:
        reasons.append(f"止损距离 {stop_dist*100:.2f}% 越界 "
                       f"[{stop_min*100:.1f}%, {stop_max*100:.1f}%]")

    # 3) 盈亏比
    checks["risk_reward"] = (plan.risk_reward or 0) >= min_rr
    if not checks["risk_reward"]:
        reasons.append(f"盈亏比 {plan.risk_reward} < {min_rr}")

    # 4) 方向与价位一致性
    tp1 = plan.targets[0] if plan.targets else None
    if plan.direction == "long":
        consistent = plan.stop_loss < lo and (tp1 is None or tp1 > hi)
    else:
        consistent = plan.stop_loss > hi and (tp1 is None or tp1 < lo)
    checks["direction_consistency"] = consistent
    if not consistent:
        reasons.append("方向与入场/止损/目标价位不一致")

    return ValidationResult(ok=not reasons, reasons=reasons, checks=checks)
