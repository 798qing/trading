"""OI + 资金费率检测（币圈特有，因子 P0-①）。进评分。

两条信息合成方向：
- 资金费率（反向读法）：费率极正=多头拥挤→偏空警惕；极负=空头拥挤→偏多警惕。
- price×OI 组合（架构十一/缺口）：
    价↑ OI↑ = 新多进场，趋势确认（顺势加强）
    价↑ OI↓ = 空头回补，虚涨（减弱）
    价↓ OI↑ = 新空进场，跌势确认
    价 OI↓ = 多头平仓，跌势减弱
OI 环比由 snapshot 注入（sources.oi.change_pct）；缺失则只用费率。
"""
from __future__ import annotations

from detectors.base import Detector, DetectorResult

_FUNDING_EXTREME = 0.0005   # 每 8h，超过视为拥挤


class OIFundingDetector(Detector):
    name = "oi_funding"

    def detect(self, snapshot, cfg, tf: str | None = None) -> DetectorResult:
        tf = tf or cfg.require("timeframes.primary")
        klines = snapshot.klines(tf)
        funding = (snapshot.sources.get("funding") or {})
        oi_src = (snapshot.sources.get("oi") or {})
        rate = funding.get("rate")
        oi_change = oi_src.get("change_pct")

        if rate is None and oi_change is None:
            return self._insufficient("无资金费率/OI 数据")

        events: list[str] = []
        score = 0      # >0 偏多, <0 偏空
        details: dict = {}

        # 资金费率（反向）
        if rate is not None:
            details["funding_rate"] = rate
            if rate >= _FUNDING_EXTREME:
                score -= 1
                events.append("funding_crowded_long")
            elif rate <= -_FUNDING_EXTREME:
                score += 1
                events.append("funding_crowded_short")

        # price×OI 组合
        if oi_change is not None and len(klines) >= 6:
            price_chg = klines[-1].close - klines[-6].close
            details["oi_change_pct"] = oi_change
            details["price_change"] = round(price_chg, 4)
            up = price_chg > 0
            oi_up = oi_change > 0
            if up and oi_up:
                score += 2; events.append("price_up_oi_up")        # 趋势确认
            elif up and not oi_up:
                score += 0; events.append("price_up_oi_down")      # 空头回补,中性
            elif (not up) and oi_up:
                score -= 2; events.append("price_down_oi_up")      # 跌势确认
            else:
                score -= 0; events.append("price_down_oi_down")    # 多头平仓,减弱

        direction = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
        strength = min(5, 1 + abs(score))
        confidence = "high" if abs(score) >= 2 else "medium" if score else "low"
        return DetectorResult(self.name, direction, strength, confidence,
                              events=events, details=details)
