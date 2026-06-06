"""Telegram 发送层 + 主动推送编排：离线 mock，不连真网。"""
from types import SimpleNamespace

import httpx
import pytest

from data.store import Store
from output.push import NEW_SIGNAL_TAG
from output.push_service import push_once, tagged_card
from output.telegram import TelegramClient, TelegramError


class _Cfg:
    def __init__(self, *, token="token", chat_id="833"):
        self.data = {
            "ops.push.dedup_window_sec": 60,
            "ops.push.cooldown_min": 240,
            "scoring.score_update_delta": 15,
        }
        self.secrets = {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat_id}

    def get(self, dotted, default=None):
        return self.data.get(dotted, default)

    def secret(self, key, default=None):
        return self.secrets.get(key, default)


def _http(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _analysis(score=72, recommendation="signal"):
    return SimpleNamespace(
        recommendation=recommendation,
        snapshot=SimpleNamespace(symbol="BTC-USDT-SWAP"),
        fusion=SimpleNamespace(score=score),
        plan=SimpleNamespace(valid=True, direction="long", entry_zone=(99.0, 101.0)),
    )


def _store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.init_db()
    return s


def _analysis_id(store):
    store.save_snapshot(
        "snap-1", 1000, "BTC-USDT-SWAP", None,
        payload={}, data_quality={"is_complete": True}, config_version="cfg_test",
    )
    return store.save_analysis(
        ts=1000, snapshot_id="snap-1", symbol="BTC-USDT-SWAP",
        score=72, direction="bullish", plan={}, llm_output=None, card_text=None,
        prompt_version="naked_chart_v1", config_version="cfg_test",
    )


def test_telegram_send_message_posts_expected_payload():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["payload"] = req.read()
        return httpx.Response(200, json={"ok": True, "result": {
            "message_id": 42, "chat": {"id": 833}
        }})

    c = TelegramClient("token", client=_http(handler))
    msg = c.send_message("833", "hello")

    assert seen["path"] == "/bottoken/sendMessage"
    assert b'"chat_id":"833"' in seen["payload"]
    assert b'"text":"hello"' in seen["payload"]
    assert msg.message_id == 42
    assert msg.chat_id == 833


def test_telegram_rejects_missing_token():
    with pytest.raises(TelegramError, match="TELEGRAM_BOT_TOKEN"):
        TelegramClient("")


def test_telegram_business_error_raises():
    c = TelegramClient("token", client=_http(lambda req: httpx.Response(
        200, json={"ok": False, "description": "chat not found"}
    )))
    with pytest.raises(TelegramError, match="chat not found"):
        c.send_message("833", "hello")


def test_telegram_delete_message_posts_expected_payload():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["payload"] = req.read()
        return httpx.Response(200, json={"ok": True, "result": True})

    c = TelegramClient("token", client=_http(handler))

    assert c.delete_message("833", 42) is True
    assert seen["path"] == "/bottoken/deleteMessage"
    assert b'"chat_id":"833"' in seen["payload"]
    assert b'"message_id":42' in seen["payload"]


def test_push_once_sends_and_records_only_after_success(tmp_path):
    s = _store(tmp_path)
    seen = {}

    def handler(req):
        seen["text"] = req.read().decode()
        return httpx.Response(200, json={"ok": True, "result": {
            "message_id": 7, "chat": {"id": 833}
        }})

    aid = _analysis_id(s)
    tg = TelegramClient("token", client=_http(handler))
    result = push_once(_analysis(), _Cfg(), s, telegram=tg, analysis_id=aid,
                       now=1000, text="CARD")

    assert result.sent is True
    assert result.decision.tag == NEW_SIGNAL_TAG
    assert result.push_event_id > 0
    assert tagged_card(NEW_SIGNAL_TAG, "CARD") == result.text
    assert "新信号" in seen["text"]
    row = s.latest_push_event(result.decision.signature)
    assert row["analysis_id"] == aid
    assert row["telegram_message_id"] == 7
    assert row["telegram_chat_id"] == "833"
    s.close()


def test_push_once_skips_wait_card_without_sending(tmp_path):
    s = _store(tmp_path)

    class Sender:
        def send_message(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("should not send")

    result = push_once(_analysis(recommendation="wait"), _Cfg(), s, telegram=Sender(),
                       now=1000, text="CARD")

    assert result.sent is False
    assert result.decision.reason == "not_signal"
    s.close()


def test_push_once_does_not_record_when_send_fails(tmp_path):
    s = _store(tmp_path)
    tg = TelegramClient("token", client=_http(lambda req: httpx.Response(
        200, json={"ok": False, "description": "blocked"}
    )))

    with pytest.raises(TelegramError, match="blocked"):
        push_once(_analysis(), _Cfg(), s, telegram=tg, now=1000, text="CARD")

    assert s.conn.execute("SELECT COUNT(*) FROM push_events").fetchone()[0] == 0
    s.close()
