"""Stage 3 full-analysis strategist.

The LLM only explains the structured package produced by Python. It must not
invent entry/stop/target prices; those remain owned by plan_builder.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from llm.provider import ChatMessage, LLMError, ProviderRouter


@dataclass(frozen=True)
class StrategyOutput:
    status: str                  # ok | fallback
    prompt_version: str
    provider: str | None
    model: str | None
    text: str
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _analysis_payload(a, cfg) -> dict[str, Any]:
    """Build a compact, deterministic package without raw klines."""
    return {
        "symbol": a.snapshot.symbol,
        "snapshot_id": a.snapshot.snapshot_id,
        "analysis_ts": a.snapshot.analysis_ts,
        "config_version": cfg.version,
        "score": a.fusion.score,
        "direction": a.fusion.direction,
        "recommendation": a.recommendation,
        "reasons": a.reasons,
        "fusion": {
            "vetoed": a.fusion.vetoed,
            "veto_reasons": a.fusion.veto_reasons,
            "hard_constraints": a.fusion.hard_constraints,
            "radar": a.fusion.radar,
            "subscores": a.fusion.subscores,
            "conflicts": a.fusion.conflicts,
            "timeframe_alignment": a.fusion.timeframe_alignment,
        },
        "plan": a.plan.to_dict(),
        "risk": {
            "warnings": a.risk.warnings,
            "position_advice": a.risk.position_advice,
        },
        "data_quality": a.snapshot.data_quality,
        "signals": {
            k: {
                "direction": v.get("direction"),
                "strength": v.get("strength"),
                "confidence": v.get("confidence"),
                "events": v.get("events", []),
                "details": v.get("details", {}),
                "warnings": v.get("warnings", []),
            }
            for k, v in sorted(a.signals.items())
        },
    }


def _messages(a, cfg) -> list[ChatMessage]:
    payload = _analysis_payload(a, cfg)
    system = (
        "你是纯分析交易策略师，只解释 Python 检测器、fusion、plan_builder 和风控结果。"
        "硬边界：不执行交易；不生成任何新的入场价、止损价、止盈价；"
        "不要修改计划价格；仓位建议只能使用保守离散措辞。"
        "如果信息冲突或数据质量不足，必须明确说降级/观望。"
        "输出中文，短段落，适合直接拼进 Telegram 卡片。"
    )
    user = (
        "请基于以下结构化包输出 full-analysis 解读。"
        "只允许引用 plan 字段里的交易计划，不要写出新的价格数字。"
        "格式：\n"
        "1. 综合判断：一句话。\n"
        "2. 关键依据：2-4 条。\n"
        "3. 风险与降级：1-3 条。\n\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def fallback_output(cfg, error: str | None = None) -> StrategyOutput:
    return StrategyOutput(
        status="fallback",
        prompt_version=str(cfg.get("ops.llm.prompt_version", "naked_chart_v1")),
        provider=None,
        model=None,
        text="LLM 不可用，以下为纯检测器结论。",
        error=error,
    )


def full_analysis(a, cfg, *, router: ProviderRouter | None = None) -> StrategyOutput:
    """Run full-analysis, falling back to naked-chart status on any LLM failure."""
    prompt_version = str(cfg.get("ops.llm.full_prompt_version", "full_analysis_v1"))
    r = router or ProviderRouter(cfg)
    try:
        resp = r.chat(_messages(a, cfg), temperature=0.2, max_tokens=900)
    except LLMError as e:
        return fallback_output(cfg, str(e))
    return StrategyOutput(
        status="ok",
        prompt_version=prompt_version,
        provider=resp.provider,
        model=resp.model,
        text=resp.content,
        error=None,
    )
