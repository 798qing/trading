"""插针主动回退：检测反向长影后撤回最近一条 Telegram 推送。

这是推送层保护，不参与评分。为了避免误删，只有同时满足：
- 最近推送有 telegram_message_id 且未撤回；
- 推送仍在配置窗口内；
- 当前已收线出现与推送方向相反的长影插针；
才调用 Telegram deleteMessage 并标记 revoked。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from common import clock


class _Deleter(Protocol):
    def delete_message(self, chat_id: str | int, message_id: int) -> bool:
        ...


@dataclass(frozen=True)
class RollbackResult:
    checked: bool
    revoked: bool
    reason: str
    push_event_id: int | None = None


def maybe_revoke_on_wick(a, cfg, store, *, telegram: _Deleter,
                         now: int | None = None) -> RollbackResult:
    n = now if now is not None else clock.now_ts()
    last = store.latest_active_push_event(a.snapshot.symbol)
    if last is None:
        return RollbackResult(True, False, "no_active_push")

    window_sec = int(cfg.get("ops.push.rollback_window_min", 30)) * 60
    if n - int(last["ts"]) > window_sec:
        return RollbackResult(True, False, "rollback_window_expired", int(last["id"]))

    hit, reason = _opposite_wick(a, cfg, str(last["direction"] or ""))
    if not hit:
        return RollbackResult(True, False, reason, int(last["id"]))

    chat_id = last["telegram_chat_id"]
    message_id = last["telegram_message_id"]
    if chat_id is None or message_id is None:
        return RollbackResult(True, False, "missing_telegram_message", int(last["id"]))

    telegram.delete_message(chat_id, int(message_id))
    store.mark_push_revoked(int(last["id"]), ts=n, reason=reason)
    return RollbackResult(True, True, reason, int(last["id"]))


def _opposite_wick(a, cfg, pushed_direction: str) -> tuple[bool, str]:
    tf = cfg.require("timeframes.primary")
    klines = a.snapshot.klines(tf)
    if not klines:
        return False, "no_kline"
    c = klines[-1]
    rng = c.high - c.low
    if rng <= 0:
        return False, "flat_kline"

    body = abs(c.close - c.open)
    upper = c.high - max(c.open, c.close)
    lower = min(c.open, c.close) - c.low
    min_wick_ratio = float(cfg.get("ops.push.rollback_wick_ratio", 0.55))
    min_body_ratio = float(cfg.get("ops.push.rollback_max_body_ratio", 0.35))

    small_body = (body / rng) <= min_body_ratio
    upper_spike = (upper / rng) >= min_wick_ratio and small_body
    lower_spike = (lower / rng) >= min_wick_ratio and small_body

    if pushed_direction == "long" and upper_spike:
        return True, "opposite_upper_wick_after_long"
    if pushed_direction == "short" and lower_spike:
        return True, "opposite_lower_wick_after_short"
    return False, "no_opposite_wick"
