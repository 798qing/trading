"""store.py — SQLite WAL 建表、K 线幂等、快照冻结、生命周期结算（D6/D9/P0-2）。"""
from data.store import Store


def _store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.init_db()
    return s


def test_wal_mode_enabled(tmp_path):
    s = _store(tmp_path)
    mode = s.conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode.lower() == "wal"
    s.close()


def test_kline_upsert_is_idempotent(tmp_path):
    s = _store(tmp_path)
    rows = [(1000, 10, 12, 9, 11, 100.0), (1900, 11, 13, 10, 12, 80.0)]
    s.upsert_klines("15m", rows)
    s.upsert_klines("15m", [(1000, 10, 99, 9, 50, 999.0)])  # 覆盖同 ts
    got = s.klines("15m", limit=10)
    assert len(got) == 2                       # 没有重复插入
    assert dict(got[0])["high"] == 99          # 被覆盖为新值
    s.close()


def test_klines_before_ts_for_replay(tmp_path):
    s = _store(tmp_path)
    s.upsert_klines("15m", [(t, 1, 1, 1, 1, 1) for t in (1000, 1900, 2800, 3700)])
    # 回测重放：只应看到 <= before_ts 的 K 线（D6/D7 防时间穿越）
    got = s.klines("15m", limit=10, before_ts=2800)
    assert [dict(r)["ts"] for r in got] == [1000, 1900, 2800]
    s.close()


def test_snapshot_roundtrip(tmp_path):
    s = _store(tmp_path)
    s.save_snapshot("snap1", 1000, "BTC-USDT-SWAP", "ranging",
                    payload={"okx": {"as_of_ts": 999}},
                    data_quality={"is_complete": True, "warnings": []},
                    config_version="cfg_abc")
    got = s.get_snapshot("snap1")
    assert got["payload"]["okx"]["as_of_ts"] == 999
    assert got["config_version"] == "cfg_abc"
    assert s.get_snapshot("missing") is None
    s.close()


def test_analysis_settle_lifecycle(tmp_path):
    s = _store(tmp_path)
    s.save_snapshot("snap1", 1000, "BTC-USDT-SWAP", None, {}, {}, "cfg_abc")
    aid = s.save_analysis(ts=1000, snapshot_id="snap1", symbol="BTC-USDT-SWAP",
                          score=72, direction="bullish",
                          plan={"entry_zone": [67000, 67400]}, llm_output=None,
                          card_text="card", prompt_version="p1",
                          config_version="cfg_abc")
    # 未结算应被扫描到
    assert [dict(r)["id"] for r in s.unsettled_analyses(before_ts=2000)] == [aid]
    s.settle_analysis(aid, outcome="correct", entry_hit=1, exit_reason="tp_hit",
                      settled_ts=5000)
    # 结算后不再出现在未结算列表
    assert s.unsettled_analyses(before_ts=9000) == []
    row = dict(s.conn.execute("SELECT * FROM analyses WHERE id=?", (aid,)).fetchone())
    assert row["outcome"] == "correct" and row["entry_hit"] == 1
    s.close()


def test_readonly_connection_sees_writes(tmp_path):
    s = _store(tmp_path)
    s.upsert_klines("1h", [(1000, 1, 1, 1, 1, 1)])
    ro = s.connect_readonly()
    assert ro.execute("SELECT COUNT(*) FROM kline_1h").fetchone()[0] == 1
    ro.close()
    s.close()


def test_push_event_roundtrip(tmp_path):
    s = _store(tmp_path)
    pid = s.save_push_event(ts=1000, symbol="BTC-USDT-SWAP",
                            signature="BTC-USDT-SWAP|long|99.0-101.0",
                            direction="long", entry_lo=99.0, entry_hi=101.0,
                            score=72, tag="新信号🆕")
    assert pid > 0
    row = s.latest_push_event("BTC-USDT-SWAP|long|99.0-101.0")
    assert dict(row)["score"] == 72
    assert s.latest_push_event("missing") is None
    s.close()
