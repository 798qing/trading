"""全链路时间基准（D8）。

存储与计算一律 UTC、整数 epoch 秒；只有展示层用 to_local() 转时区。
检测器防前视（D7）依赖 last_closed_ts()：永远只取“已收线”K 线。
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# 各周期秒数（统一口径，K 线/快照/收线判定共用）
TF_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def tf_seconds(tf: str) -> int:
    """周期字符串 → 秒。未知周期抛 KeyError（不静默兜底，避免错位）。"""
    return TF_SECONDS[tf]


def now_utc() -> datetime:
    """当前时刻，带 UTC tzinfo 的 aware datetime。"""
    return datetime.now(timezone.utc)


def now_ts() -> int:
    """当前 epoch 秒（int）。系统内部统一用它，不用 naive datetime。"""
    return int(now_utc().timestamp())


def from_ts(ts: int) -> datetime:
    """epoch 秒 → aware UTC datetime。"""
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def floor_ts(ts: int, tf: str) -> int:
    """把 ts 向下取整到所属周期的起点（K 线开盘时间）。"""
    sec = tf_seconds(tf)
    return ts - (ts % sec)


def last_closed_ts(tf: str, now: int | None = None) -> int:
    """返回最近一根**已收线** K 线的开盘 ts（D7 防前视的核心）。

    当前正在形成、尚未收线的那根永远不返回。
    例：15m 周期，现在 09:07 → 返回 08:45 那根（08:45–09:00 已收线）。
    """
    n = now_ts() if now is None else now
    sec = tf_seconds(tf)
    current_open = n - (n % sec)   # 当前未收线那根的开盘
    return current_open - sec      # 上一根（已收线）


def is_closed(open_ts: int, tf: str, now: int | None = None) -> bool:
    """给定 K 线开盘 ts，判断它现在是否已收线。"""
    n = now_ts() if now is None else now
    return open_ts + tf_seconds(tf) <= n


def to_local(dt_or_ts: datetime | int, tz: str = "Asia/Shanghai") -> datetime:
    """展示层专用：UTC → 本地时区 aware datetime。存储层禁止调用。"""
    dt = from_ts(dt_or_ts) if isinstance(dt_or_ts, int) else dt_or_ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz))
