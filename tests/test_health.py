"""health.py — 生产闭环健康检查。"""
from ops.health import check_health, render_health
from data.store import Store


class _Cfg:
    def __init__(self):
        self.data = {
            "meta.symbol": "BTC-USDT-SWAP",
            "timeframes.primary": "15m",
            "plan_builder.signal_ttl_klines": 4,
        }

    def require(self, dotted):
        return self.data[dotted]

    def get(self, dotted, default=None):
        return self.data.get(dotted, default)


def _store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.init_db()
    return s


def _seed_fresh(store, *, now):
    latest_closed = now - (now % 900) - 900
    store.upsert_klines("15m", [(latest_closed, 1, 2, 1, 2, 1)])
    store.save_snapshot("snap1", latest_closed, "BTC-USDT-SWAP", None, {}, {}, "cfg")
    store.save_analysis(
        ts=latest_closed, snapshot_id="snap1", symbol="BTC-USDT-SWAP", score=70,
        direction="bullish", plan={"valid": True}, llm_output=None, card_text=None,
        prompt_version="p1", config_version="cfg",
    )
    return latest_closed


def test_health_ok_when_hot_db_is_fresh(tmp_path):
    s = _store(tmp_path)
    now = 10_000
    _seed_fresh(s, now=now)

    report = check_health(s, _Cfg(), now=now)

    assert report["status"] == "ok"
    assert report["checks"]["database"]["wal_mode"] == "wal"
    assert report["checks"]["klines"]["ok"] is True
    assert report["checks"]["settlement"]["unsettled_due"] == 0
    assert "健康检查 BTC-USDT-SWAP status=ok" in render_health(report)
    s.close()


def test_health_warns_on_stale_klines(tmp_path):
    s = _store(tmp_path)
    now = 10_000
    _seed_fresh(s, now=now)
    old_ts = now - 10 * 900
    s.upsert_klines("15m", [(old_ts, 1, 2, 1, 2, 1)])
    s.conn.execute("DELETE FROM kline_15m WHERE ts>?", (old_ts,))

    report = check_health(s, _Cfg(), now=now)

    assert report["status"] == "warn"
    assert report["checks"]["klines"]["ok"] is False
    assert report["checks"]["klines"]["lag_sec"] > report["checks"]["klines"]["max_stale_sec"]
    s.close()


def test_health_warns_on_due_unsettled_analyses(tmp_path):
    s = _store(tmp_path)
    now = 20_000
    _seed_fresh(s, now=now)
    s.save_snapshot("old", 1000, "BTC-USDT-SWAP", None, {}, {}, "cfg")
    s.save_analysis(
        ts=1000, snapshot_id="old", symbol="BTC-USDT-SWAP", score=72,
        direction="bullish", plan={"valid": True}, llm_output=None,
        card_text=None, prompt_version="p1", config_version="cfg",
    )

    report = check_health(s, _Cfg(), now=now)

    assert report["status"] == "warn"
    assert report["checks"]["settlement"]["ok"] is False
    assert report["checks"]["settlement"]["unsettled_due"] == 1
    s.close()
