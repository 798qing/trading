"""宏观联动/事件窗口检测（阶段3）。

当前 repo 尚无宏观 collector；检测器消费可选 snapshot.sources.macro。
当宏观源缺失时只返回 no_macro_event=True，避免误触发否决。
"""
from __future__ import annotations

from detectors.base import Detector, DetectorResult


class MacroDetector(Detector):
    name = "macro"

    def detect(self, snapshot, cfg, tf: str | None = None) -> DetectorResult:
        src = snapshot.sources.get("macro") or {}
        if not src or src.get("status") == "unavailable":
            return DetectorResult(
                self.name, "neutral", 1, "low",
                details={"no_macro_event": True, "data_quality": "unavailable"},
                warnings=["缺宏观联动源，按无宏观事件窗口处理"],
            )

        no_macro_event = not bool(src.get("event_in_window", False))
        risk_state = str(src.get("risk_state") or "neutral")
        corr_nasdaq = src.get("btc_nasdaq_corr")
        corr_dxy = src.get("btc_dxy_corr")

        direction = "neutral"
        strength = 2
        events: list[str] = []
        if risk_state == "risk_on":
            direction, strength = "bullish", 3
            events.append("risk_on")
        elif risk_state == "risk_off":
            direction, strength = "bearish", 3
            events.append("risk_off")

        if not no_macro_event:
            events.append("macro_event_window")
            strength = max(strength, 4)

        return DetectorResult(
            self.name, direction, strength, "medium", events=events,
            details={
                "risk_state": risk_state,
                "btc_nasdaq_corr": corr_nasdaq,
                "btc_dxy_corr": corr_dxy,
                "event_name": src.get("event_name"),
                "event_in_window": src.get("event_in_window", False),
                "no_macro_event": no_macro_event,
                "data_quality": src.get("status", "exact"),
            },
        )
