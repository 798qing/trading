"""sample_progress.py — 阶段3采样进度/防空转巡检。"""

from data.store import Store
from ops.sample_progress import (
    render_sample_progress,
    sample_progress_json,
    sample_progress_report,
)


class _Cfg:
    version = "cfg_current"

    def __init__(self):
        self.data = {
            "meta": {"symbol": "BTC-USDT-SWAP"},
            "timeframes": {"primary": "15m"},
            "plan_builder": {
                "backtest_sample_min_score": 40,
                "signal_ttl_klines": 4,
            },
            "scoring": {"standard_card_score": 60},
            "ops": {"auto_weight": {"min_settled_signals": 2}},
            "display": {"timezone": "UTC"},
        }

    def get(self, dotted, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def require(self, dotted):
        val = self.get(dotted)
        if val is None:
            raise KeyError(dotted)
        return val


def _store(tmp_path):
    s = Store(tmp_path / "sample-progress.db")
    s.init_db()
    return s


def _seed(store, *, ts, snapshot_id, score, direction="bullish",
          plan=None, config_version="cfg_current", outcome=None,
          entry_hit=0):
    store.save_snapshot(
        snapshot_id, ts, "BTC-USDT-SWAP", "trending", {}, {}, config_version,
    )
    aid = store.save_analysis(
        ts=ts,
        snapshot_id=snapshot_id,
        symbol="BTC-USDT-SWAP",
        score=score,
        direction=direction,
        plan=plan if plan is not None else {
            "valid": False,
            "direction": None,
            "key_levels": {},
        },
        llm_output=None,
        card_text=None,
        prompt_version="p1",
        config_version=config_version,
    )
    if outcome is not None:
        store.settle_analysis(
            aid,
            outcome=outcome,
            entry_hit=entry_hit,
            exit_reason="tp_hit" if outcome == "correct" else "expired",
            settled_ts=ts + 3600,
            outcome_note="pnl_net=1.000%" if entry_hit else None,
        )
    return aid


def _valid_long():
    return {
        "valid": True,
        "direction": "long",
        "entry_zone": [100.0, 101.0],
        "stop_loss": 98.0,
        "targets": [104.0],
        "risk_reward": 2.0,
    }


def test_progress_waits_for_market_when_no_score_qualified_rows(tmp_path):
    store = _store(tmp_path)
    now = 2_000_000
    _seed(store, ts=now - 100, snapshot_id="low", score=23)
    _seed(store, ts=now - 50, snapshot_id="old-cfg", score=55,
          plan=_valid_long(), config_version="cfg_old")

    report = sample_progress_report(store, _Cfg(), days=30, now=now)

    assert report["status"] == "waiting_for_market"
    assert report["counts"]["total_analyses_window"] == 2
    assert report["counts"]["current_config_analyses"] == 1
    assert report["counts"]["score_qualified_directional"] == 0
    assert report["counts"]["remaining_to_gate"] == 2
    assert "status=waiting_for_market" in render_sample_progress(report, timezone="UTC")
    assert '"snapshot_id": "low"' in sample_progress_json(report)
    store.close()


def test_progress_reports_settlement_backlog_before_sample_collection(tmp_path):
    store = _store(tmp_path)
    now = 2_000_000
    old_due = now - 10 * 900
    _seed(store, ts=old_due, snapshot_id="due", score=45, plan=_valid_long())

    report = sample_progress_report(store, _Cfg(), days=30, now=now)

    assert report["status"] == "settlement_backlog"
    assert report["counts"]["due_unsettled_current_config"] == 1
    assert report["counts"]["valid_sample_plans"] == 1
    store.close()


def test_progress_is_ready_after_entered_sample_gate(tmp_path):
    store = _store(tmp_path)
    now = 2_000_000
    _seed(store, ts=now - 6000, snapshot_id="win", score=45,
          plan=_valid_long(), outcome="correct", entry_hit=1)
    _seed(store, ts=now - 5000, snapshot_id="partial", score=50,
          plan=_valid_long(), outcome="partial", entry_hit=1)
    _seed(store, ts=now - 4000, snapshot_id="expired", score=48,
          plan=_valid_long(), outcome="expired", entry_hit=0)

    report = sample_progress_report(store, _Cfg(), days=30, now=now)

    assert report["status"] == "ready_for_weight_review"
    assert report["counts"]["valid_sample_plans"] == 3
    assert report["counts"]["settled_sample_plans"] == 3
    assert report["counts"]["entered_sample_plans"] == 2
    assert report["counts"]["remaining_to_gate"] == 0
    store.close()
