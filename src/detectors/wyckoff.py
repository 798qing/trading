"""威科夫检测（第一版 = 候选，D4）。

第一版只输出 *_candidate 事件、needs_confirmation:true，**direction 恒 neutral**，
因此天然不进 fusion 主评分（fusion 跳过 neutral）。只作观望卡观察字段，**不触发推送**，
等回测证明命中率稳定后再升级进评分（阶段3）。

候选识别（保守子集）：
- spring_candidate：跌破前 swing 低后**收回**其上（积累阶段假跌破）→ 看多假设。
- utad_candidate：升破前 swing 高后**收回**其下（派发阶段假突破）→ 看空假设。
"""
from __future__ import annotations

from detectors.base import Detector, DetectorResult, find_swings


class WyckoffDetector(Detector):
    name = "wyckoff"

    def detect(self, snapshot, cfg, tf: str | None = None) -> DetectorResult:
        tf = tf or cfg.require("timeframes.primary")
        klines = snapshot.klines(tf)
        sp = cfg.get("detectors.structure", {})
        lookback = sp.get("swing_lookback", 5)
        confirm = sp.get("swing_confirm_delay", 2)

        if len(klines) < 2 * lookback + 5:
            return self._insufficient(f"{tf} K线不足以判威科夫")

        highs, lows = find_swings(klines, lookback, confirm)
        last = klines[-1]
        events: list[str] = []
        details: dict = {"phase_hypothesis": "undetermined", "needs_confirmation": True,
                         "confirmation_tf": tf}

        if lows:
            swing_low = lows[-1].price
            if last.low < swing_low and last.close > swing_low:
                events.append("spring_candidate")
                details.update(phase_hypothesis="accumulation", swing_low=swing_low,
                               invalid_if=f"下一根 {tf} 收盘跌破 {round(swing_low, 2)}")
        if highs and not events:
            swing_high = highs[-1].price
            if last.high > swing_high and last.close < swing_high:
                events.append("utad_candidate")
                details.update(phase_hypothesis="distribution", swing_high=swing_high,
                               invalid_if=f"下一根 {tf} 收盘升破 {round(swing_high, 2)}")

        # D4：永远 neutral、低强度，不进主评分、不推送；仅观察字段。
        strength = 2 if events else 1
        return DetectorResult(self.name, direction="neutral", strength=strength,
                              confidence="low", events=events, details=details)
