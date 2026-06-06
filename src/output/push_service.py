"""主动推送编排：判定 → 渲染 → Telegram 发送 → 记录冷却事件。

推送策略在 output.push；本模块只在发送成功后 record_push，避免失败请求污染
去重/冷却窗口。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from output import card_builder as cb
from output.push import PushDecision, evaluate, record_push
from output.telegram import TelegramClient, TelegramError, TelegramMessage


class _Sender(Protocol):
    def send_message(self, chat_id: str | int, text: str, *,
                     disable_web_page_preview: bool = True) -> TelegramMessage:
        ...


@dataclass(frozen=True)
class PushResult:
    decision: PushDecision
    sent: bool
    message: TelegramMessage | None = None
    push_event_id: int | None = None
    text: str | None = None


def tagged_card(tag: str | None, card_text: str) -> str:
    """在卡片顶部加推送标签；无 tag 时保持原文。"""
    return f"{tag}\n{card_text}" if tag else card_text


def push_once(a, cfg, store, *, telegram: _Sender | None = None,
              analysis_id: int | None = None, now: int | None = None,
              text: str | None = None) -> PushResult:
    """按阶段2规则推送一次分析结果。

    返回 sent=False 表示策略不允许推；Telegram 失败会抛 TelegramError，且不会写
    push_events。
    """
    decision = evaluate(a, cfg, store, now=now)
    if not decision.should_push:
        return PushResult(decision=decision, sent=False)

    chat_id = cfg.secret("TELEGRAM_CHAT_ID")
    if chat_id is None or str(chat_id).strip() == "":
        raise TelegramError("缺少 TELEGRAM_CHAT_ID")

    card_text = text if text is not None else cb.render(a, cfg, quick=False)
    send_text = tagged_card(decision.tag, card_text)
    own_sender = telegram is None
    sender = telegram or TelegramClient(cfg.secret("TELEGRAM_BOT_TOKEN"))
    try:
        msg = sender.send_message(chat_id, send_text, disable_web_page_preview=True)
    finally:
        if own_sender and hasattr(sender, "close"):
            sender.close()
    event_id = record_push(store, a, decision, analysis_id=analysis_id, now=now)
    return PushResult(
        decision=decision,
        sent=True,
        message=msg,
        push_event_id=event_id,
        text=send_text,
    )
