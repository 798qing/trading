"""RSI 检测：超买/超卖（架构 3.2）。进评分（权重低 0.8）。

方向取均值回归读法：超卖→偏多、超买→偏空。
强趋势下 RSI 长期极值的反向压制由 risk.py 的例外处理（ADX>30 时不降级）。
"""
from __future__ import annotations

from common.ta import rsi as compute_rsi
from detectors.base import Detector, DetectorResult


class RSIDetector(Detector):
    name = "rsi"

    def detect(self, snapshot, cfg, tf: str | None = None) -> DetectorResult:
        tf = tf or cfg.require("timeframes.primary")
        klines = snapshot.klines(tf)
        params = cfg.get("detectors.rsi", {})
        period = params.get("period", 14)
        ob = params.get("overbought", 70)
        os_ = params.get("oversold", 30)

        closes = [k.close for k in klines]
        r = compute_rsi(closes, period)
        if r is None:
            return self._insufficient(f"{tf} K线不足以算 RSI")

        if r <= os_:
            direction, strength, confidence, events = "bullish", 3, "medium", ["oversold"]
        elif r >= ob:
            direction, strength, confidence, events = "bearish", 3, "medium", ["overbought"]
        else:
            direction, strength, confidence, events = "neutral", 2, "low", []

        return DetectorResult(
            self.name, direction, strength, confidence, events=events,
            details={"rsi": round(r, 2), "overbought": ob, "oversold": os_},
        )
