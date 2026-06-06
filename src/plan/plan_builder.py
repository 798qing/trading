"""交易计划生成 —— 价格的唯一来源（D3）。

输入：fusion 结果（方向）+ snapshot（标记价/已收线K线）+ 各检测器 details（swing/fib/ATR）。
输出：入场区间 / 止损 / 目标 / 失效条件，每个价格附 source_levels 标签可追溯。
LLM 不参与任何价格生成；validate.py 再做数值校验与降级。

方向为 neutral / veto 观望时仍输出 key_levels（关键支撑阻力），供观望卡使用。
分数低于正式信号阈值、但达到 backtest_sample_min_score 的非 veto 方向性
观望，也会生成纸面计划，供回测闭环采样；最终推送仍由 recommendation 控制。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from common.ta import atr as compute_atr


@dataclass
class TradePlan:
    direction: str                       # "long" | "short" | "none"
    valid: bool
    entry_zone: list[float] | None = None
    stop_loss: float | None = None
    targets: list[float] = field(default_factory=list)
    invalid_if: str | None = None
    risk_reward: float | None = None
    source_levels: dict[str, list[str]] = field(default_factory=dict)
    key_levels: dict[str, list] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction, "valid": self.valid,
            "entry_zone": self.entry_zone, "stop_loss": self.stop_loss,
            "targets": self.targets, "invalid_if": self.invalid_if,
            "risk_reward": self.risk_reward, "source_levels": self.source_levels,
            "key_levels": self.key_levels, "notes": self.notes,
        }


def _r(x: float, nd: int = 1) -> float:
    return round(x, nd)


def _collect_levels(signals: dict, ref: float, klines) -> tuple[list, list]:
    """收集带来源标签的关键位，分成阻力(>ref)与支撑(<ref)。

    返回 (resistances, supports)，元素为 (price, source)，按距 ref 由近到远。
    """
    levels: list[tuple[float, str]] = []
    struct = signals.get("structure", {}).get("details", {})
    if struct.get("last_swing_high") is not None:
        levels.append((struct["last_swing_high"], "swing_high"))
    if struct.get("last_swing_low") is not None:
        levels.append((struct["last_swing_low"], "swing_low"))
    fib = signals.get("fib", {}).get("details", {})
    for name, price in (fib.get("levels") or {}).items():
        tag = "fib_ext" if name.startswith("ext") else "fib_ret"
        levels.append((price, tag))

    # 兜底：无任何结构位时用近 20 根高低
    if not levels and klines:
        window = klines[-20:]
        levels.append((max(k.high for k in window), "recent_high"))
        levels.append((min(k.low for k in window), "recent_low"))

    res = sorted([(p, s) for p, s in levels if p > ref], key=lambda x: x[0] - ref)
    sup = sorted([(p, s) for p, s in levels if p < ref], key=lambda x: ref - x[0])
    return res, sup


def build_plan(fusion, snapshot, signals: dict, cfg) -> TradePlan:
    pb = cfg.get("plan_builder", {})
    stop_min = pb.get("stop_min_pct", 0.5) / 100.0
    stop_max = pb.get("stop_max_pct", 5.0) / 100.0
    min_rr = pb.get("min_risk_reward", 1.5)
    atr_period = pb.get("atr_period", 14)
    primary = cfg.require("timeframes.primary")
    klines = snapshot.klines(primary)

    mark = (snapshot.sources.get("mark") or {}).get("price")
    ref = mark if mark else (klines[-1].close if klines else None)
    if ref is None:
        return TradePlan("none", valid=False, notes=["无参考价（标记价/收盘均缺）"])

    resistances, supports = _collect_levels(signals, ref, klines)
    key_levels = {
        "resistances": [[_r(p), s] for p, s in resistances[:2]],
        "supports": [[_r(p), s] for p, s in supports[:2]],
    }

    direction = fusion.direction
    sample_min = pb.get("backtest_sample_min_score")
    score = getattr(fusion, "score", 0) or 0
    sample_plan = (
        fusion.recommendation == "wait"
        and direction in ("bullish", "bearish")
        and not getattr(fusion, "vetoed", False)
        and sample_min is not None
        and score >= sample_min
    )
    # 无方向 / veto / 低于采样下限的观望：只给关键位，不出可执行计划
    if direction not in ("bullish", "bearish") or (
        fusion.recommendation == "wait" and not sample_plan
    ):
        reason = "无方向"
        if fusion.recommendation == "wait":
            reason = "veto/观望"
        return TradePlan("none", valid=False, key_levels=key_levels,
                         notes=[f"不出计划：{reason}"])

    atr_val = compute_atr(klines, atr_period) or ref * 0.005
    is_long = direction == "bullish"
    breakout = "breakout_up" in signals.get("structure", {}).get("events", []) or \
               "breakdown" in signals.get("structure", {}).get("events", [])

    if is_long:
        plan = _build_long(ref, atr_val, resistances, supports, signals, breakout,
                           stop_min, stop_max, min_rr, primary)
    else:
        plan = _build_short(ref, atr_val, resistances, supports, signals, breakout,
                            stop_min, stop_max, min_rr, primary)
    plan.key_levels = key_levels
    if sample_plan:
        plan.notes.append(
            f"观望采样计划：score={score} < signal_threshold，"
            "仅用于回测闭环，不触发推送"
        )
    return plan


def _rr(entry_ref: float, stop: float, tp: float) -> float:
    risk = abs(entry_ref - stop)
    return abs(tp - entry_ref) / risk if risk > 0 else 0.0


def _build_long(ref, atr_val, resistances, supports, signals, breakout,
                stop_min, stop_max, min_rr, primary) -> TradePlan:
    struct = signals.get("structure", {}).get("details", {})
    swing_high = struct.get("last_swing_high")
    swing_low = struct.get("last_swing_low")
    notes: list[str] = []

    # 入场：突破→回踩突破位；否则→最近支撑上方
    band = max(atr_val * 0.3, ref * 0.001)
    if breakout and swing_high and swing_high < ref:
        entry_lo, entry_hi = swing_high, ref
        entry_src = ["breakout_retest"]
    elif supports:
        anchor, src = supports[0]
        entry_lo, entry_hi = anchor, anchor + band
        entry_src = [src]
    else:
        entry_lo, entry_hi = ref - band, ref
        entry_src = ["mark"]
    entry_lo, entry_hi = sorted((entry_lo, entry_hi))

    # 止损：swing_low 与 ATR 取更远者，再夹到 [stop_min, stop_max]
    raw_stop = min(swing_low, entry_lo - atr_val) if swing_low else entry_lo - atr_val
    stop = _clamp_stop_long(raw_stop, entry_lo, stop_min, stop_max)
    stop_src = ["swing_low", "ATR"] if swing_low else ["ATR"]

    # 目标：以入场区上沿(最差成交)为 RR 基准，与 validate 的 tp1>entry_hi 口径一致。
    # 仅采用落在上沿之上的阻力作 TP1，否则按 min_rr 投影。
    risk = entry_hi - stop
    if resistances and resistances[0][0] > entry_hi:
        tp1, tp1_src = resistances[0][0], [resistances[0][1]]
    else:
        tp1, tp1_src = entry_hi + risk * min_rr, ["rr_projection"]
    if _rr(entry_hi, stop, tp1) < min_rr:
        tp1 = entry_hi + risk * min_rr
        tp1_src = ["rr_projection"]
        notes.append(f"TP1 按最小盈亏比 {min_rr} 投影")
    tp2 = resistances[1][0] if len(resistances) > 1 and resistances[1][0] > tp1 \
        else tp1 + risk

    rr = _rr(entry_hi, stop, tp1)
    return TradePlan(
        "long", valid=True,
        entry_zone=[_r(entry_lo), _r(entry_hi)], stop_loss=_r(stop),
        targets=[_r(tp1), _r(tp2)], invalid_if=f"{primary} 收盘跌破 {_r(stop)}",
        risk_reward=round(rr, 2),
        source_levels={"entry": entry_src, "stop": stop_src,
                       "target": tp1_src + ["fib_ext/swing"]},
        notes=notes,
    )


def _build_short(ref, atr_val, resistances, supports, signals, breakout,
                 stop_min, stop_max, min_rr, primary) -> TradePlan:
    struct = signals.get("structure", {}).get("details", {})
    swing_high = struct.get("last_swing_high")
    swing_low = struct.get("last_swing_low")
    notes: list[str] = []

    band = max(atr_val * 0.3, ref * 0.001)
    if breakout and swing_low and swing_low > ref:
        entry_lo, entry_hi = ref, swing_low
        entry_src = ["breakdown_retest"]
    elif resistances:
        anchor, src = resistances[0]
        entry_lo, entry_hi = anchor - band, anchor
        entry_src = [src]
    else:
        entry_lo, entry_hi = ref, ref + band
        entry_src = ["mark"]
    entry_lo, entry_hi = sorted((entry_lo, entry_hi))

    raw_stop = max(swing_high, entry_hi + atr_val) if swing_high else entry_hi + atr_val
    stop = _clamp_stop_short(raw_stop, entry_hi, stop_min, stop_max)
    stop_src = ["swing_high", "ATR"] if swing_high else ["ATR"]

    # RR 以入场区下沿(最差成交)为基准，与 validate 的 tp1<entry_lo 口径一致。
    risk = stop - entry_lo
    if supports and supports[0][0] < entry_lo:
        tp1, tp1_src = supports[0][0], [supports[0][1]]
    else:
        tp1, tp1_src = entry_lo - risk * min_rr, ["rr_projection"]
    if _rr(entry_lo, stop, tp1) < min_rr:
        tp1 = entry_lo - risk * min_rr
        tp1_src = ["rr_projection"]
        notes.append(f"TP1 按最小盈亏比 {min_rr} 投影")
    tp2 = supports[1][0] if len(supports) > 1 and supports[1][0] < tp1 \
        else tp1 - risk

    rr = _rr(entry_lo, stop, tp1)
    return TradePlan(
        "short", valid=True,
        entry_zone=[_r(entry_lo), _r(entry_hi)], stop_loss=_r(stop),
        targets=[_r(tp1), _r(tp2)], invalid_if=f"{primary} 收盘升破 {_r(stop)}",
        risk_reward=round(rr, 2),
        source_levels={"entry": entry_src, "stop": stop_src,
                       "target": tp1_src + ["fib_ext/swing"]},
        notes=notes,
    )


def _clamp_stop_long(stop, entry_lo, stop_min, stop_max) -> float:
    dist = (entry_lo - stop) / entry_lo
    if dist < stop_min:
        return entry_lo * (1 - stop_min)
    if dist > stop_max:
        return entry_lo * (1 - stop_max)
    return stop


def _clamp_stop_short(stop, entry_hi, stop_min, stop_max) -> float:
    dist = (stop - entry_hi) / entry_hi
    if dist < stop_min:
        return entry_hi * (1 + stop_min)
    if dist > stop_max:
        return entry_hi * (1 + stop_max)
    return stop
