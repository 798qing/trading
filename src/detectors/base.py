"""检测器基类 + 统一输出 schema + swing 防前视工具（架构 3.6 / P0-3）。

统一 schema（架构 3.6）：
    module / direction / strength(1-5) / confidence / events / details / warnings

防前视（P0-3）：swing 高低点确认延迟 N 根 —— 第 i 根的 swing 在第 (i+N) 根才“可见”。
回测重放时，快照最后一根为 L，则只有满足 i + confirm_delay <= L 的 swing 才返回，
杜绝“用了尚未确认的极值点”。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

Direction = str  # "bullish" | "bearish" | "neutral"
Confidence = str  # "high" | "medium" | "low"


@dataclass
class DetectorResult:
    module: str
    direction: Direction = "neutral"
    strength: int = 1                      # 1-5
    confidence: Confidence = "low"
    events: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "direction": self.direction,
            "strength": self.strength,
            "confidence": self.confidence,
            "events": list(self.events),
            "details": dict(self.details),
            "warnings": list(self.warnings),
        }


class Detector:
    """检测器基类。子类实现 detect()，返回 DetectorResult。

    约定：检测器只读 snapshot 冻结的已收线 K 线（D6/D7），不自行取数。
    """
    name: str = "base"

    def detect(self, snapshot, cfg) -> DetectorResult:  # pragma: no cover
        raise NotImplementedError

    # 数据不足时的标准空结果
    def _insufficient(self, msg: str) -> DetectorResult:
        return DetectorResult(module=self.name, direction="neutral", strength=1,
                              confidence="low", warnings=[msg])


@dataclass
class Swing:
    idx: int
    price: float
    ts: int
    kind: str  # "high" | "low"


def find_swings(klines: Sequence, lookback: int, confirm_delay: int
                ) -> tuple[list[Swing], list[Swing]]:
    """分形 swing：klines[i] 为窗口 [i-lookback, i+lookback] 内的极值。

    仅返回已“可见”的 swing（i + confirm_delay <= 最后一根索引），实现 P0-3 防前视。
    返回 (highs, lows)，各按 idx 升序。
    """
    highs: list[Swing] = []
    lows: list[Swing] = []
    n = len(klines)
    if n < 2 * lookback + 1:
        return highs, lows
    last = n - 1
    lag = max(lookback, confirm_delay)
    for i in range(lookback, n - lookback):
        if i + lag > last:                 # 尚未确认/可见 → 跳过（防前视）
            continue
        window = klines[i - lookback:i + lookback + 1]
        hi = max(k.high for k in window)
        lo = min(k.low for k in window)
        if klines[i].high == hi:
            highs.append(Swing(i, klines[i].high, klines[i].ts, "high"))
        if klines[i].low == lo:
            lows.append(Swing(i, klines[i].low, klines[i].ts, "low"))
    return highs, lows
