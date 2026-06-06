"""Telegram Bot API 发送层（阶段2：主动推送出口）。

只封装 sendMessage，不接管轮询；部署上仍可让 hermes 作为唯一 bot 入口。
测试中可注入 httpx.Client + MockTransport，避免真实联网。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

TELEGRAM_BASE_URL = "https://api.telegram.org"


class TelegramError(RuntimeError):
    """Telegram 网络、鉴权、业务码或解析错误。"""


@dataclass(frozen=True)
class TelegramMessage:
    message_id: int | None
    chat_id: str | int | None
    raw: dict[str, Any]


class TelegramClient:
    def __init__(self, token: str | None, base_url: str = TELEGRAM_BASE_URL,
                 timeout: float = 10.0, client: httpx.Client | None = None):
        self.token = (token or "").strip()
        if not self.token:
            raise TelegramError("缺少 TELEGRAM_BOT_TOKEN")
        self.base_url = base_url.rstrip("/")
        self._own_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def send_message(self, chat_id: str | int, text: str, *,
                     disable_web_page_preview: bool = True) -> TelegramMessage:
        if chat_id is None or str(chat_id).strip() == "":
            raise TelegramError("缺少 TELEGRAM_CHAT_ID")
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        path = f"/bot{self.token}/sendMessage"
        try:
            resp = self._client.post(self.base_url + path, json=payload)
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise TelegramError(f"Telegram sendMessage 请求失败: {e}") from e

        if body.get("ok") is not True:
            desc = body.get("description") or body.get("error_code") or "unknown"
            raise TelegramError(f"Telegram sendMessage 业务错误: {desc}")

        result = body.get("result") or {}
        chat = result.get("chat") or {}
        return TelegramMessage(
            message_id=result.get("message_id"),
            chat_id=chat.get("id"),
            raw=result,
        )

    def close(self) -> None:
        if self._own_client:
            self._client.close()

    def __enter__(self) -> "TelegramClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
