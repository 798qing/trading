"""结构检测：HH/HL/LH/LL 识别 + 结构性突破（架构 3.1）。

只用 primary 周期已收线 K 线 + 防前视 swing（P0-3）。
direction 来自结构序列；突破方向触发 events，缩量突破由 volume 检测器另行判定。
"""
from __future__ import annotations

from detectors.base import Detector, DetectorResult, find_swings


class StructureDetector(Detector):
    name = "structure"

    def detect(self, snapshot, cfg) -> DetectorResult:
        tf = cfg.require("timeframes.primary")
        klines = snapshot.klines(tf)
        params = cfg.get("detectors.structure", {})
        lookback = params.get("swing_lookback", 5)
        confirm = params.get("swing_confirm_delay", 2)

        if len(klines) < 2 * lookback + 5:
            return self._insufficient(f"{tf} K线不足以判结构")

        highs, lows = find_swings(klines, lookback, confirm)
        if len(highs) < 2 or len(lows) < 2:
            return DetectorResult(self.name, "neutral", 2, "low",
                                  details={"structure": "indeterminate",
                                           "swing_highs": len(highs),
                                           "swing_lows": len(lows)})

        h_prev, h_last = highs[-2].price, highs[-1].price
        l_prev, l_last = lows[-2].price, lows[-1].price
        hh, hl = h_last > h_prev, l_last > l_prev
        lh, ll = h_last < h_prev, l_last < l_prev

        if hh and hl:
            structure, direction, strength = "uptrend", "bullish", 4
        elif lh and ll:
            structure, direction, strength = "downtrend", "bearish", 4
        else:
            structure, direction, strength = "range", "neutral", 2

        # 结构性突破：最后已收线收盘 突破 最近 swing 高/低
        close = klines[-1].close
        events: list[str] = []
        last_high = highs[-1].price
        last_low = lows[-1].price
        if close > last_high:
            events.append("breakout_up")
            if direction != "bearish":
                direction, strength = "bullish", max(strength, 4)
        elif close < last_low:
            events.append("breakdown")
            if direction != "bullish":
                direction, strength = "bearish", max(strength, 4)

        confidence = "high" if strength >= 4 else "medium"
        return DetectorResult(
            self.name, direction, strength, confidence, events=events,
            details={
                "structure": structure,
                "last_swing_high": last_high,
                "last_swing_low": last_low,
                "close": close,
                "hh": hh, "hl": hl, "lh": lh, "ll": ll,
            },
        )
