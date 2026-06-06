"""清算/杠杆拥挤代理检测（阶段3）。

当前没有逐笔清算流 collector，先消费 CoinGlass 多空比作为 liquidation proxy：
多头明显拥挤 → 反向偏空警惕；空头明显拥挤 → 反向偏多警惕。
缺数据时保持 neutral，不阻塞主链路。
"""
from __future__ import annotations

from detectors.base import Detector, DetectorResult


class LiquidationDetector(Detector):
    name = "liquidation"

    def detect(self, snapshot, cfg, tf: str | None = None) -> DetectorResult:
        src = snapshot.sources.get("long_short") or {}
        ratio = src.get("long_short_ratio")
        long_ratio = src.get("long_ratio")
        short_ratio = src.get("short_ratio")
        if ratio is None and long_ratio is None and short_ratio is None:
            return self._insufficient("缺 CoinGlass 多空比，清算拥挤代理不可用")

        p = cfg.get("detectors.liquidation", {})
        crowded_long = p.get("crowded_long_ratio", 1.5)
        crowded_short = p.get("crowded_short_ratio", 0.67)
        hot_account = p.get("crowded_account_ratio", 0.62)

        events: list[str] = []
        direction = "neutral"
        strength = 2
        confidence = "medium"

        long_hot = ((ratio is not None and ratio >= crowded_long)
                    or (long_ratio is not None and long_ratio >= hot_account))
        short_hot = ((ratio is not None and ratio <= crowded_short)
                     or (short_ratio is not None and short_ratio >= hot_account))

        if long_hot and not short_hot:
            direction = "bearish"
            events.append("long_crowding")
            strength = 4 if (ratio or 0) >= crowded_long * 1.25 else 3
        elif short_hot and not long_hot:
            direction = "bullish"
            events.append("short_crowding")
            strength = 4 if ratio is not None and ratio <= crowded_short * 0.75 else 3
        else:
            events.append("crowding_balanced")
            confidence = "low"

        return DetectorResult(
            self.name, direction, strength, confidence, events=events,
            details={
                "long_ratio": long_ratio,
                "short_ratio": short_ratio,
                "long_short_ratio": ratio,
                "data_quality": src.get("status", "exact"),
            },
        )
