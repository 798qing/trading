"""量能检测：量价关系 + 暴量 + 突破量能确认（架构 3.1）。

关键职责之一：判定“突破是否缩量”——这是 structural_veto 的输入（D5）。
details.breakout_volume_ok 由 fusion 读取用于硬约束。
"""
from __future__ import annotations

from common.ta import sma
from detectors.base import Detector, DetectorResult


class VolumeDetector(Detector):
    name = "volume"

    def detect(self, snapshot, cfg) -> DetectorResult:
        tf = cfg.require("timeframes.primary")
        klines = snapshot.klines(tf)
        params = cfg.get("detectors.volume", {})
        spike_ratio = params.get("spike_ratio", 2.0)
        breakout_min = params.get("breakout_min_ratio", 1.2)
        lookback = 20

        if len(klines) < lookback + 1:
            return self._insufficient(f"{tf} K线不足以判量能")

        vols = [k.volume for k in klines]
        avg = sma(vols[:-1], lookback)            # 不含当根，避免自我稀释
        last = klines[-1]
        if not avg or avg <= 0:
            return self._insufficient("均量为 0")

        ratio = last.volume / avg
        spike = ratio >= spike_ratio
        up_candle = last.close >= last.open

        # 方向：仅在暴量时给方向（量本身无向，配合收盘方向）
        if spike:
            direction = "bullish" if up_candle else "bearish"
            strength = 5 if ratio >= spike_ratio * 1.5 else 4
            confidence = "high"
        else:
            direction = "neutral"
            strength = 2 if ratio >= 1.0 else 1
            confidence = "medium" if ratio >= 1.0 else "low"

        events: list[str] = []
        if spike:
            events.append("volume_spike")

        # 突破量能确认：是否存在结构突破由 fusion 综合，这里给出“当根量能是否够格”
        breakout_volume_ok = ratio >= breakout_min

        return DetectorResult(
            self.name, direction, strength, confidence, events=events,
            details={
                "vol_ratio": round(ratio, 3),
                "avg_volume": round(avg, 4),
                "spike": spike,
                "up_candle": up_candle,
                "breakout_volume_ok": breakout_volume_ok,
                "breakout_min_ratio": breakout_min,
            },
        )
