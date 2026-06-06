"""期现基差检测（因子 P0-②）。进评分。

basis% = (永续标记价 − 现货价) / 现货价 × 100
- 正基差（永续升水/contango）：杠杆多头情绪偏热 → 温和偏多，过大则过热警惕。
- 负基差（永续贴水/backwardation）：偏空/避险。
现货价由 snapshot.sources.spot 注入（OKX 现货 ticker）。缺现货 → 不输出（观察缺失）。
"""
from __future__ import annotations

from detectors.base import Detector, DetectorResult

_HOT = 0.15      # 基差% 过热阈值（升水过大，杠杆多头拥挤）


class BasisDetector(Detector):
    name = "basis"

    def detect(self, snapshot, cfg, tf: str | None = None) -> DetectorResult:
        mark = (snapshot.sources.get("mark") or {}).get("price")
        spot = (snapshot.sources.get("spot") or {}).get("price")
        if not mark or not spot or spot <= 0:
            return self._insufficient("缺现货/标记价，无法算基差")

        basis_pct = (mark - spot) / spot * 100
        events: list[str] = []
        if basis_pct > 0:
            direction = "bullish"
            if basis_pct >= _HOT:
                events.append("contango_hot")          # 升水过热
                direction, strength, confidence = "bearish", 2, "low"   # 过热反偏空警惕
            else:
                strength, confidence = 3, "medium"
                events.append("contango")
        elif basis_pct < 0:
            direction, strength, confidence = "bearish", 3, "medium"
            events.append("backwardation")
        else:
            direction, strength, confidence = "neutral", 1, "low"

        return DetectorResult(self.name, direction, strength, confidence, events=events,
                              details={"basis_pct": round(basis_pct, 4),
                                       "mark": mark, "spot": spot})
