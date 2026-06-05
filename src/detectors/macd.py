"""MACD 检测：金叉/死叉 + 零轴位置 + 柱状方向（架构 3.2）。进评分。"""
from __future__ import annotations

from common.ta import macd as compute_macd
from detectors.base import Detector, DetectorResult


class MACDDetector(Detector):
    name = "macd"

    def detect(self, snapshot, cfg, tf: str | None = None) -> DetectorResult:
        tf = tf or cfg.require("timeframes.primary")
        klines = snapshot.klines(tf)
        closes = [k.close for k in klines]
        res = compute_macd(closes)
        if res is None:
            return self._insufficient(f"{tf} K线不足以算 MACD")
        dif, dea, hist = res

        golden = dif[-2] <= dea[-2] and dif[-1] > dea[-1]
        death = dif[-2] >= dea[-2] and dif[-1] < dea[-1]
        above_zero = dif[-1] > 0

        if golden:
            direction, strength, confidence, events = "bullish", 4, "high", ["golden_cross"]
        elif death:
            direction, strength, confidence, events = "bearish", 4, "high", ["death_cross"]
        elif hist[-1] > 0:
            direction, strength, confidence, events = "bullish", 2, "medium", []
        elif hist[-1] < 0:
            direction, strength, confidence, events = "bearish", 2, "medium", []
        else:
            direction, strength, confidence, events = "neutral", 1, "low", []

        # 零轴回踩：金叉发生在零轴之上更可靠
        if events and ((golden and above_zero) or (death and not above_zero)):
            strength = 5
            events.append("zero_axis_aligned")

        return DetectorResult(
            self.name, direction, strength, confidence, events=events,
            details={"dif": round(dif[-1], 4), "dea": round(dea[-1], 4),
                     "hist": round(hist[-1], 4), "above_zero": above_zero},
        )
