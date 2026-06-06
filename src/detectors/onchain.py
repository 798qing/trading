"""链上交易所净流检测（阶段3）。

CryptoQuant exchange netflow：净流入交易所偏空（潜在卖压），净流出偏多（供给离场）。
缺数据时保持 neutral。
"""
from __future__ import annotations

from detectors.base import Detector, DetectorResult


class OnchainDetector(Detector):
    name = "onchain"

    def detect(self, snapshot, cfg, tf: str | None = None) -> DetectorResult:
        src = snapshot.sources.get("exchange_netflow") or {}
        netflow = src.get("netflow_total")
        if netflow is None:
            return self._insufficient("缺 CryptoQuant exchange_netflow，链上净流不可用")

        p = cfg.get("detectors.onchain", {})
        threshold = float(p.get("netflow_btc_threshold", 100.0))
        strong = float(p.get("netflow_btc_strong", threshold * 5))

        abs_flow = abs(float(netflow))
        if abs_flow < threshold:
            direction, strength, confidence, events = "neutral", 2, "low", ["netflow_muted"]
        elif netflow > 0:
            direction, events = "bearish", ["exchange_netflow_in"]
            strength = 4 if abs_flow >= strong else 3
            confidence = "high" if abs_flow >= strong else "medium"
        else:
            direction, events = "bullish", ["exchange_netflow_out"]
            strength = 4 if abs_flow >= strong else 3
            confidence = "high" if abs_flow >= strong else "medium"

        return DetectorResult(
            self.name, direction, strength, confidence, events=events,
            details={
                "netflow_total": netflow,
                "inflow_total": src.get("inflow_total"),
                "outflow_total": src.get("outflow_total"),
                "exchange": src.get("exchange"),
                "window": src.get("window"),
                "threshold": threshold,
                "data_quality": src.get("status", "exact"),
            },
        )
