"""对数收益率（D10）—— 全系统波动率/相关性/夏普的统一计算底座。

口径一致、可加、对称。所有需要“收益”的地方都从这里取，不各自 (P1/P0-1)。
价格须为正；非正价格视为数据异常，直接抛错而非静默跳过。
"""
from __future__ import annotations

import math


def log_return(p_prev: float, p_curr: float) -> float:
    """单期对数收益率 ln(P_t / P_{t-1})。"""
    if p_prev <= 0 or p_curr <= 0:
        raise ValueError(f"价格须为正：p_prev={p_prev}, p_curr={p_curr}")
    return math.log(p_curr / p_prev)


def log_returns(prices: list[float]) -> list[float]:
    """价格序列 → 对数收益率序列（长度 = len(prices) - 1）。"""
    if len(prices) < 2:
        return []
    return [log_return(prices[i - 1], prices[i]) for i in range(1, len(prices))]


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs: list[float], sample: bool = True) -> float:
    """标准差。sample=True 用 n-1（样本）；序列过短返回 0。"""
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (n - 1 if sample else n)
    return math.sqrt(var)


def realized_vol(rets: list[float], periods_per_year: float) -> float:
    """已实现波动率（年化）= 对数收益率标准差 × sqrt(每年期数)。

    periods_per_year 例：15m K 线 → 365*24*4 = 35040。
    """
    return stdev(rets) * math.sqrt(periods_per_year)


def cumulative_return(rets: list[float]) -> float:
    """对数收益率可加：累计 = exp(sum) - 1，返回简单收益率口径。"""
    return math.expm1(sum(rets))
