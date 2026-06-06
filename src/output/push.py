"""推送资格判定：阈值、去重、冷却、评分大幅变化更新。

本模块只负责策略，不负责 Telegram/HTTP 发送。调用方真正发出卡片后再
record_push()，这样失败的发送不会污染冷却记录。
"""
from __future__ import annotations

from dataclasses import dataclass

from common import clock

NEW_SIGNAL_TAG = "新信号🆕"
UPDATE_TAG = "信号更新🔁"


@dataclass(frozen=True)
class PushDecision:
    should_push: bool
    tag: str | None
    reason: str
    signature: str | None = None


def signal_signature(a) -> str | None:
    """同方向 + 同入场区间的稳定签名。无有效交易计划则无签名。"""
    p = a.plan
    if not p.valid or p.direction not in ("long", "short") or not p.entry_zone:
        return None
    lo, hi = p.entry_zone
    return f"{a.snapshot.symbol}|{p.direction}|{lo:.1f}-{hi:.1f}"


def evaluate(a, cfg, store, *, now: int | None = None) -> PushDecision:
    """判断本次分析是否应该触发推送。

    规则：
    - 只有 recommendation=signal 且 plan.valid 才能推。
    - 60s 内同签名直接去重。
    - 冷却期内同签名不重复推；若评分变化 > score_update_delta，则以更新推送。
    - 冷却期外视为新信号。
    """
    sig = signal_signature(a)
    if a.recommendation != "signal" or sig is None:
        return PushDecision(False, None, "not_signal", sig)

    n = now if now is not None else clock.now_ts()
    last = store.latest_push_event(sig)
    if last is None:
        return PushDecision(True, NEW_SIGNAL_TAG, "new_signal", sig)

    elapsed = n - int(last["ts"])
    dedup_sec = int(cfg.get("ops.push.dedup_window_sec", 60))
    if elapsed < dedup_sec:
        return PushDecision(False, None, "dedup_window", sig)

    cooldown_sec = int(cfg.get("ops.push.cooldown_min", 240)) * 60
    score_delta = abs((a.fusion.score or 0) - (last["score"] or 0))
    update_delta = int(cfg.get("scoring.score_update_delta", 15))
    if elapsed < cooldown_sec:
        if score_delta > update_delta:
            return PushDecision(True, UPDATE_TAG, "score_update", sig)
        return PushDecision(False, None, "cooldown", sig)

    return PushDecision(True, NEW_SIGNAL_TAG, "new_signal", sig)


def record_push(store, a, decision: PushDecision, *,
                analysis_id: int | None = None, now: int | None = None,
                telegram_message_id: int | None = None,
                telegram_chat_id: str | int | None = None) -> int | None:
    """实际推送成功后写入去重记录。未推送则不写。"""
    if not decision.should_push or not decision.signature:
        return None
    n = now if now is not None else clock.now_ts()
    lo, hi = a.plan.entry_zone
    return store.save_push_event(
        ts=n, symbol=a.snapshot.symbol, signature=decision.signature,
        direction=a.plan.direction, entry_lo=lo, entry_hi=hi,
        score=a.fusion.score, tag=decision.tag, analysis_id=analysis_id,
        telegram_message_id=telegram_message_id, telegram_chat_id=telegram_chat_id,
    )
