"""ADX 趋势强度检测（架构 3.2，权重 0.5）。

只判断“趋势有无/强弱”，**不判断方向**（direction 恒 neutral），方向由 structure 等负责。
details.adx 供 fusion 读取做 contextual_veto（ADX < adx_min → 无趋势否决，wyckoff 确认事件豁免）。
details.plus_di/minus_di 仅作背景，供 risk.py 参考。
"""
from __future__ import annotations

from common.ta import adx as compute_adx
from detectors.base import Detector, DetectorResult


class ADXDetector(Detector):
    name = "adx"

    def detect(self, snapshot, cfg) -> DetectorResult:
        tf = cfg.require("timeframes.primary")
        klines = snapshot.klines(tf)
        params = cfg.get("detectors.adx", {})
        period = params.get("period", 14)
        strong = params.get("strong", 30)
        adx_min = cfg.get("hard_constraints.contextual_veto.adx_min", 18)

        res = compute_adx(klines, period)
        if res is None:
            return self._insufficient(f"{tf} K线不足以算 ADX（需 ~{2*period+1} 根）")
        adx_val, pdi, mdi = res

        if adx_val >= strong:
            classification, strength, confidence = "strong", 5, "high"
        elif adx_val >= adx_min:
            classification, strength, confidence = "trending", 3, "medium"
        else:
            classification, strength, confidence = "no_trend", 1, "high"

        return DetectorResult(
            self.name, direction="neutral", strength=strength, confidence=confidence,
            details={
                "adx": round(adx_val, 2),
                "plus_di": round(pdi, 2),
                "minus_di": round(mdi, 2),
                "classification": classification,
                "adx_min": adx_min,
                "strong_threshold": strong,
            },
        )
