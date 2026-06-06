"""插针主动回退：离线 mock，不连 Telegram。"""
from types import SimpleNamespace

from data.snapshot import Kline
from data.store import Store
from output.rollback import maybe_revoke_on_wick


class _Cfg:
    def __init__(self):
        self.data = {
            "timeframes.primary": "15m",
            "ops.push.rollback_window_min": 30,
            "ops.push.rollback_wick_ratio": 0.55,
            "ops.push.rollback_max_body_ratio": 0.35,
        }

    def get(self, dotted, default=None):
        return self.data.get(dotted, default)

    def require(self, dotted):
        return self.data[dotted]


class _Telegram:
    def __init__(self):
        self.deleted = []

    def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))
        return True


def _store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.init_db()
    return s


def _analysis(kline):
    snap = SimpleNamespace(
        symbol="BTC-USDT-SWAP",
        klines=lambda tf: [kline],
    )
    return SimpleNamespace(snapshot=snap)


def test_revoke_long_push_on_opposite_upper_wick(tmp_path):
    s = _store(tmp_path)
    pid = s.save_push_event(
        ts=1000, symbol="BTC-USDT-SWAP", signature="sig", direction="long",
        entry_lo=99, entry_hi=101, score=72, tag="新信号",
        telegram_message_id=42, telegram_chat_id="833",
    )
    tg = _Telegram()
    k = Kline(ts=1900, open=100, high=112, low=99, close=101, volume=1)

    result = maybe_revoke_on_wick(_analysis(k), _Cfg(), s, telegram=tg, now=1100)

    assert result.revoked is True
    assert result.push_event_id == pid
    assert tg.deleted == [("833", 42)]
    assert s.latest_active_push_event("BTC-USDT-SWAP") is None
    s.close()


def test_no_revoke_without_opposite_wick(tmp_path):
    s = _store(tmp_path)
    s.save_push_event(
        ts=1000, symbol="BTC-USDT-SWAP", signature="sig", direction="long",
        entry_lo=99, entry_hi=101, score=72, tag="新信号",
        telegram_message_id=42, telegram_chat_id="833",
    )
    tg = _Telegram()
    k = Kline(ts=1900, open=100, high=103, low=99, close=102, volume=1)

    result = maybe_revoke_on_wick(_analysis(k), _Cfg(), s, telegram=tg, now=1100)

    assert result.revoked is False
    assert result.reason == "no_opposite_wick"
    assert tg.deleted == []
    assert s.latest_active_push_event("BTC-USDT-SWAP") is not None
    s.close()
