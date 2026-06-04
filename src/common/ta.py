"""技术指标底层计算（无业务依赖，纯数值）。

供检测器与 plan_builder 共用：ATR（止损/计划用）、ADX（趋势强度）。
输入为带 .high/.low/.close 的 K 线对象序列（如 snapshot.Kline），升序。
样本不足时返回 None，调用方据此降级而非崩溃。
"""
from __future__ import annotations

from typing import Sequence


def sma(values: Sequence[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def true_ranges(klines: Sequence) -> list[float]:
    """TR_t = max(H-L, |H-prevC|, |L-prevC|)。长度 = len-1。"""
    trs: list[float] = []
    for i in range(1, len(klines)):
        h, l, pc = klines[i].high, klines[i].low, klines[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return trs


def _wilder_first(values: Sequence[float], period: int) -> float:
    return sum(values[:period]) / period


def atr(klines: Sequence, period: int = 14) -> float | None:
    """Wilder ATR，返回最新值。需至少 period+1 根 K 线。"""
    trs = true_ranges(klines)
    if len(trs) < period:
        return None
    a = _wilder_first(trs, period)
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a


def adx(klines: Sequence, period: int = 14
        ) -> tuple[float, float, float] | None:
    """Wilder ADX，返回 (adx, +DI, -DI) 最新值。需约 2*period+1 根。"""
    n = len(klines)
    if n < 2 * period + 1:
        return None

    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    for i in range(1, n):
        up = klines[i].high - klines[i - 1].high
        down = klines[i - 1].low - klines[i].low
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        h, l, pc = klines[i].high, klines[i].low, klines[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    # Wilder 平滑（用累加滚动）
    tr_s = _wilder_first(trs, period)
    pdm_s = _wilder_first(plus_dm, period)
    mdm_s = _wilder_first(minus_dm, period)

    dxs: list[float] = []
    for i in range(period, len(trs)):
        tr_s = tr_s - tr_s / period + trs[i]
        pdm_s = pdm_s - pdm_s / period + plus_dm[i]
        mdm_s = mdm_s - mdm_s / period + minus_dm[i]
        if tr_s == 0:
            dxs.append(0.0)
            continue
        pdi = 100 * pdm_s / tr_s
        mdi = 100 * mdm_s / tr_s
        denom = pdi + mdi
        dxs.append(100 * abs(pdi - mdi) / denom if denom else 0.0)

    if len(dxs) < period:
        return None
    adx_val = _wilder_first(dxs, period)
    for dx in dxs[period:]:
        adx_val = (adx_val * (period - 1) + dx) / period

    # 最新 +DI/-DI（用最后一次平滑值）
    pdi = 100 * pdm_s / tr_s if tr_s else 0.0
    mdi = 100 * mdm_s / tr_s if tr_s else 0.0
    return adx_val, pdi, mdi
