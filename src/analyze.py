"""分析流水线编排：snapshot → 检测 → 大周期判向 → fusion → plan → 校验风控 → 决策。

这是 bot/precompute 的统一入口。把检测器、聚合、计划、风控串成一次完整分析，
并补齐之前的缺口：对 higher 周期各跑一次结构判向，喂给 fusion 的 structural_veto（D5）。
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from data.snapshot import collect_and_freeze
from detectors.adx import ADXDetector
from detectors.basis import BasisDetector
from detectors.candle import CandleDetector
from detectors.fib import FibDetector
from detectors.macd import MACDDetector
from detectors.oi_funding import OIFundingDetector
from detectors.rsi import RSIDetector
from detectors.structure import StructureDetector
from detectors.volume import VolumeDetector
from detectors.wyckoff import WyckoffDetector
from fusion.fusion import FusionResult, fuse
from plan.plan_builder import TradePlan, build_plan
from review.risk import RiskResult, decide, review_risk
from review.validate import ValidationResult, validate_plan

# wyckoff 第一版只作观察字段(D4)：direction=neutral，fusion 自动跳过不进评分。
_PRIMARY_DETECTORS = (StructureDetector, VolumeDetector, ADXDetector, FibDetector,
                      CandleDetector, MACDDetector, RSIDetector, WyckoffDetector,
                      OIFundingDetector, BasisDetector)


@dataclass
class Analysis:
    snapshot: object
    signals: dict                  # module -> DetectorResult.to_dict()
    fusion: FusionResult
    plan: TradePlan
    validation: ValidationResult
    risk: RiskResult
    recommendation: str            # 最终建议（validate/risk 降级后）
    reasons: list[str]
    llm_output: dict | None = None


def _htf_directions(snapshot, cfg) -> dict[str, str]:
    """对 higher 周期各跑一次结构判向（供 fusion 大周期否决）。"""
    out: dict[str, str] = {}
    sd = StructureDetector()
    for tf in cfg.get("timeframes.higher", []):
        if snapshot.klines(tf):
            out[tf] = sd.detect(snapshot, cfg, tf=tf).direction
    return out


def analyze(store, cfg, okx=None, *, snapshot=None, now=None) -> Analysis:
    """跑一次完整分析。传 snapshot 走重放；否则用 okx 实时采集冻结。"""
    if snapshot is None:
        if okx is None:
            raise ValueError("analyze 需要 okx 或 snapshot 之一")
        snapshot = collect_and_freeze(store, cfg, okx, now=now)

    signals = {d().name: d().detect(snapshot, cfg).to_dict()
               for d in _PRIMARY_DETECTORS}
    htf = _htf_directions(snapshot, cfg)

    fusion = fuse(signals, cfg, htf_directions=htf,
                  data_quality=snapshot.data_quality)
    plan = build_plan(fusion, snapshot, signals, cfg)
    validation = validate_plan(plan, snapshot, cfg)
    risk = review_risk(plan, fusion, snapshot, cfg)
    recommendation, reasons = decide(fusion, validation, risk)

    # 回填 risk_reward 子分（架构十七节）
    if plan.risk_reward:
        fusion.subscores["risk_reward"] = min(100, int(plan.risk_reward / 3 * 100))

    return Analysis(snapshot=snapshot, signals=signals, fusion=fusion, plan=plan,
                    validation=validation, risk=risk,
                    recommendation=recommendation, reasons=reasons)


def persist(store, cfg, a: Analysis) -> int:
    """落库：analyses（含 plan/版本指纹）+ 各检测器 signals。返回 analysis_id。"""
    snap = a.snapshot
    for module, sig in a.signals.items():
        store.save_signal(ts=snap.analysis_ts, snapshot_id=snap.snapshot_id,
                          module=module, direction=sig.get("direction"),
                          strength=sig.get("strength"),
                          confidence=sig.get("confidence"), details=sig.get("details"))
    llm_payload = a.llm_output
    prompt_version = (
        llm_payload.get("prompt_version")
        if isinstance(llm_payload, dict) and llm_payload.get("prompt_version")
        else cfg.prompt_version
    )
    return store.save_analysis(
        ts=snap.analysis_ts, snapshot_id=snap.snapshot_id, symbol=snap.symbol,
        score=a.fusion.score, direction=a.fusion.direction,
        plan=a.plan.to_dict(),
        llm_output=(json.dumps(llm_payload, ensure_ascii=False)
                    if llm_payload is not None else None),
        card_text=None,
        prompt_version=prompt_version, config_version=cfg.version,
    )
