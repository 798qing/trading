"""斐波那契检测：回撤位 + 扩展位 + 与当前价共振（架构 3.3）。

斐波是“位置”信息，不主动给方向（direction=neutral），但当价格正落在关键回撤位附近时
给出更高 strength，并把 levels 交给 plan_builder 作为关键位候选（source_levels）。
"""
from __future__ import annotations

from detectors.base import Detector, DetectorResult, find_swings


class FibDetector(Detector):
    name = "fib"

    def detect(self, snapshot, cfg) -> DetectorResult:
        tf = cfg.require("timeframes.primary")
        klines = snapshot.klines(tf)
        fp = cfg.get("detectors.fib", {})
        sp = cfg.get("detectors.structure", {})
        levels_r = fp.get("levels", [0.382, 0.5, 0.618, 0.786])
        ext_r = fp.get("extensions", [1.272, 1.618])
        tol_pct = fp.get("confluence_tolerance_pct", 0.5)
        lookback = sp.get("swing_lookback", 5)
        confirm = sp.get("swing_confirm_delay", 2)

        if len(klines) < 2 * lookback + 5:
            return self._insufficient(f"{tf} K线不足以算斐波")

        highs, lows = find_swings(klines, lookback, confirm)
        if not highs or not lows:
            return self._insufficient("无可见 swing 高/低")

        sh, sl = highs[-1], lows[-1]
        hi, lo = sh.price, sl.price
        if hi <= lo:
            return self._insufficient("swing 区间退化（high<=low）")

        rng = hi - lo
        up_leg = sh.idx > sl.idx          # 最近一段是 低→高（上行）

        levels: dict[str, float] = {}
        for r in levels_r:
            levels[f"ret_{r}"] = (hi - rng * r) if up_leg else (lo + rng * r)
        for r in ext_r:
            levels[f"ext_{r}"] = (hi + rng * (r - 1)) if up_leg else (lo - rng * (r - 1))

        close = klines[-1].close
        tol = close * tol_pct / 100.0
        nearest_name, nearest_price, nearest_dist = None, None, None
        for name, price in levels.items():
            d = abs(close - price)
            if nearest_dist is None or d < nearest_dist:
                nearest_name, nearest_price, nearest_dist = name, price, d

        at_key_level = nearest_dist is not None and nearest_dist <= tol
        strength = 4 if at_key_level else 2
        confidence = "medium" if at_key_level else "low"
        events = ["at_fib_level"] if at_key_level else []

        return DetectorResult(
            self.name, direction="neutral", strength=strength, confidence=confidence,
            events=events,
            details={
                "swing_high": hi,
                "swing_low": lo,
                "up_leg": up_leg,
                "levels": {k: round(v, 2) for k, v in levels.items()},
                "nearest_level": nearest_name,
                "nearest_price": round(nearest_price, 2) if nearest_price else None,
                "at_key_level": at_key_level,
                "tolerance": round(tol, 2),
            },
        )
