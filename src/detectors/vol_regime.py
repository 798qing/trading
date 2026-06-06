"""波动率状态检测（阶段3）。

只判断行情背景，不给多空方向。使用 ATR% 对当前 primary 周期做低/常态/高波动分类。
"""
from __future__ import annotations

from common.ta import atr
from detectors.base import Detector, DetectorResult


class VolRegimeDetector(Detector):
    name = "vol_regime"

    def detect(self, snapshot, cfg, tf: str | None = None) -> DetectorResult:
        tf = tf or cfg.require("timeframes.primary")
        klines = snapshot.klines(tf)
        p = cfg.get("detectors.vol_regime", {})
        period = int(p.get("atr_period", cfg.get("plan_builder.atr_period", 14)))
        high = float(p.get("high_atr_pct", 1.2))
        low = float(p.get("low_atr_pct", 0.25))

        val = atr(klines, period)
        close = klines[-1].close if klines else None
        if val is None or not close:
            return self._insufficient(f"{tf} K线不足以判断波动状态")

        atr_pct = val / close * 100
        if atr_pct >= high:
            regime, strength, confidence = "high_vol", 5, "high"
        elif atr_pct <= low:
            regime, strength, confidence = "low_vol", 2, "medium"
        else:
            regime, strength, confidence = "normal_vol", 3, "medium"

        return DetectorResult(
            self.name, "neutral", strength, confidence, events=[regime],
            details={
                "regime": regime,
                "atr": round(val, 4),
                "atr_pct": round(atr_pct, 4),
                "high_atr_pct": high,
                "low_atr_pct": low,
            },
        )
