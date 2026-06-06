"""CoinGlass 多空比仓位倾斜检测（阶段3）。

LiquidationDetector 已把极端多/空拥挤作为反向清算风险处理。这里刻意只消费
“未到拥挤阈值”的温和账户倾斜，作为情绪/仓位背景低权重进评分；一旦进入极端区间，
本检测器转为 neutral，把反向风险留给 liquidation，避免同源数据重复加权。
"""
from __future__ import annotations

from detectors.base import Detector, DetectorResult


class LongShortDetector(Detector):
    name = "long_short"

    def detect(self, snapshot, cfg, tf: str | None = None) -> DetectorResult:
        src = snapshot.sources.get("long_short") or {}
        ratio = src.get("long_short_ratio")
        long_ratio = src.get("long_ratio")
        short_ratio = src.get("short_ratio")
        if ratio is None and long_ratio is None and short_ratio is None:
            return self._insufficient("缺 CoinGlass 多空比，仓位倾斜不可用")

        p = cfg.get("detectors.long_short", {})
        bullish_ratio = float(p.get("bullish_ratio", 1.1))
        bearish_ratio = float(p.get("bearish_ratio", 0.91))
        strong_bullish_ratio = float(p.get("strong_bullish_ratio", 1.25))
        strong_bearish_ratio = float(p.get("strong_bearish_ratio", 0.8))
        account_bias = float(p.get("account_bias_ratio", 0.54))
        strong_account_bias = float(p.get("strong_account_bias_ratio", 0.58))

        extreme_long = float(p.get("extreme_long_ratio", 1.5))
        extreme_short = float(p.get("extreme_short_ratio", 0.67))
        extreme_account = float(p.get("extreme_account_ratio", 0.62))

        long_extreme = ((ratio is not None and ratio >= extreme_long)
                        or (long_ratio is not None and long_ratio >= extreme_account))
        short_extreme = ((ratio is not None and ratio <= extreme_short)
                         or (short_ratio is not None and short_ratio >= extreme_account))

        events: list[str] = []
        direction = "neutral"
        strength = 2
        confidence = "low"

        if long_extreme or short_extreme:
            if long_extreme:
                events.append("long_bias_extreme")
            if short_extreme:
                events.append("short_bias_extreme")
            events.append("deferred_to_liquidation")
        else:
            long_bias = ((ratio is not None and ratio >= bullish_ratio)
                         or (long_ratio is not None and long_ratio >= account_bias))
            short_bias = ((ratio is not None and ratio <= bearish_ratio)
                          or (short_ratio is not None and short_ratio >= account_bias))

            if long_bias and not short_bias:
                direction = "bullish"
                events.append("long_bias")
                strong = ((ratio is not None and ratio >= strong_bullish_ratio)
                          or (long_ratio is not None
                              and long_ratio >= strong_account_bias))
                strength = 3 if strong else 2
                confidence = "medium" if strong else "low"
            elif short_bias and not long_bias:
                direction = "bearish"
                events.append("short_bias")
                strong = ((ratio is not None and ratio <= strong_bearish_ratio)
                          or (short_ratio is not None
                              and short_ratio >= strong_account_bias))
                strength = 3 if strong else 2
                confidence = "medium" if strong else "low"
            else:
                events.append("long_short_balanced")

        return DetectorResult(
            self.name, direction, strength, confidence, events=events,
            details={
                "long_ratio": long_ratio,
                "short_ratio": short_ratio,
                "long_short_ratio": ratio,
                "data_quality": src.get("status", "exact"),
            },
        )
