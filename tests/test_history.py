"""history.py — 最近分析/结算流水查询。"""
from data.store import Store
from ops.history import history_json, history_report, render_history


class _Cfg:
    def require(self, dotted):
        assert dotted == "meta.symbol"
        return "BTC-USDT-SWAP"

    def get(self, dotted, default=None):
        return default


def _store(tmp_path):
    s = Store(tmp_path / "history.db")
    s.init_db()
    return s


def _seed(store, *, ts, snapshot_id, symbol="BTC-USDT-SWAP",
          outcome=None, outcome_note=None, plan=None):
    store.save_snapshot(snapshot_id, ts, symbol, "trending", {}, {}, "cfg")
    analysis_id = store.save_analysis(
        ts=ts,
        snapshot_id=snapshot_id,
        symbol=symbol,
        score=72,
        direction="bullish",
        plan=plan or {
            "valid": True,
            "direction": "bullish",
            "entry_zone": [100.0, 101.0],
            "stop_loss": 98.0,
            "targets": [104.0],
            "risk_reward": 2.0,
        },
        llm_output=None,
        card_text=None,
        prompt_version="p1",
        config_version="cfg_a",
    )
    if outcome is not None:
        store.settle_analysis(
            analysis_id,
            outcome=outcome,
            entry_hit=1 if outcome in {"correct", "wrong", "partial"} else 0,
            exit_reason="tp_hit" if outcome == "correct" else "expired",
            settled_ts=ts + 3600,
            outcome_note=outcome_note,
        )
    return analysis_id


def test_history_report_filters_days_symbol_and_limit(tmp_path):
    store = _store(tmp_path)
    now = 2_000_000
    _seed(store, ts=now - 35 * 86400, snapshot_id="old", outcome="correct")
    _seed(store, ts=now - 200, snapshot_id="new1", outcome="wrong",
          outcome_note="pnl_net=-1.25%")
    _seed(store, ts=now - 100, snapshot_id="new2", outcome="correct",
          outcome_note="pnl_net=2.50%")
    _seed(store, ts=now - 50, snapshot_id="other", symbol="ETH-USDT-SWAP",
          outcome="correct")

    report = history_report(store, _Cfg(), days=30, limit=1, now=now)

    assert report["total_matches"] == 2
    assert report["limit"] == 1
    assert [item["snapshot_id"] for item in report["items"]] == ["new2"]
    assert report["items"][0]["pnl_net_pct"] == 2.5
    store.close()


def test_history_report_filters_outcome_and_pending(tmp_path):
    store = _store(tmp_path)
    now = 2_000_000
    _seed(store, ts=now - 300, snapshot_id="pending")
    _seed(store, ts=now - 200, snapshot_id="win", outcome="correct")
    _seed(store, ts=now - 100, snapshot_id="loss", outcome="wrong")

    pending = history_report(store, _Cfg(), days=None, outcome="pending", now=now)
    wrong = history_report(store, _Cfg(), days=None, outcome="wrong", now=now)

    assert pending["total_matches"] == 1
    assert pending["items"][0]["outcome"] == "pending"
    assert wrong["total_matches"] == 1
    assert wrong["items"][0]["snapshot_id"] == "loss"
    store.close()


def test_render_history_and_json_are_useful(tmp_path):
    store = _store(tmp_path)
    now = 2_000_000
    _seed(store, ts=now - 100, snapshot_id="win", outcome="correct",
          outcome_note="pnl_net=1.00%")

    report = history_report(store, _Cfg(), days=7, now=now)
    text = render_history(report, timezone="UTC")

    assert "历史查询 BTC-USDT-SWAP (7d)" in text
    assert "outcome=correct" in text
    assert "pnl=1.00%" in text
    assert '"snapshot_id": "win"' in history_json(report)
    store.close()
