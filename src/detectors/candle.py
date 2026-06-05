"""K 线形态检测（架构 3.1）：吞没 / 锤子 / 射击之星 / 十字星。进评分。

形态多需下一根确认 → details.needs_confirmation=True，confidence 偏 medium。
"""
from __future__ import annotations

from detectors.base import Detector, DetectorResult


class CandleDetector(Detector):
    name = "candle"

    def detect(self, snapshot, cfg, tf: str | None = None) -> DetectorResult:
        tf = tf or cfg.require("timeframes.primary")
        klines = snapshot.klines(tf)
        if len(klines) < 3:
            return self._insufficient(f"{tf} K线不足以判形态")

        c, p = klines[-1], klines[-2]
        rng = c.high - c.low
        if rng <= 0:
            return DetectorResult(self.name, "neutral", 1, "low",
                                  details={"pattern": "flat"})
        body = abs(c.close - c.open)
        upper = c.high - max(c.open, c.close)
        lower = min(c.open, c.close) - c.low
        bull = c.close > c.open
        bear = c.close < c.open

        pattern, direction, strength, needs_conf = "none", "neutral", 1, False

        # 吞没（当根实体包裹前一根**真实体**，方向相反；前根须有实体）
        if bull and p.close < p.open and c.close >= p.open and c.open <= p.close:
            pattern, direction, strength = "bullish_engulfing", "bullish", 4
        elif bear and p.close > p.open and c.open >= p.close and c.close <= p.open:
            pattern, direction, strength = "bearish_engulfing", "bearish", 4
        # 锤子（下影长、实体小靠上）
        elif lower >= 2 * body and upper <= body and body > 0:
            pattern, direction, strength, needs_conf = "hammer", "bullish", 3, True
        # 射击之星（上影长、实体小靠下）
        elif upper >= 2 * body and lower <= body and body > 0:
            pattern, direction, strength, needs_conf = "shooting_star", "bearish", 3, True
        # 十字星（实体极小 = 犹豫）
        elif body <= rng * 0.1:
            pattern, direction, strength, needs_conf = "doji", "neutral", 2, True

        confidence = "high" if (strength >= 4 and not needs_conf) else \
                     "medium" if strength >= 3 else "low"
        events = [pattern] if pattern != "none" else []

        return DetectorResult(
            self.name, direction, strength, confidence, events=events,
            details={"pattern": pattern, "needs_confirmation": needs_conf,
                     "body": round(body, 4), "upper_wick": round(upper, 4),
                     "lower_wick": round(lower, 4)},
        )
