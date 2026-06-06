"""weighting.py — 阶段3 auto-weight 建议器。"""
import pytest

from backtest.weighting import render_weight_report, weight_report
from data.store import Store


class _Cfg:
    version = "cfg_test"

    def __init__(self):
        self.data = {
            "meta": {"symbol": "BTC-USDT-SWAP"},
            "fusion": {
                "base_weights": {
                    "structure": 1.5,
                    "volume": 2.0,
                }
            },
            "ops": {"auto_weight": {"min_settled_signals": 30}},
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
    s = Store(tmp_path / "t.db")
    s.init_db()
    return s


def _settled_with_signal(store, *, ts, module, outcome, note=None):
    sid = f"snap-{ts}-{module}"
    store.save_snapshot(sid, ts, "BTC-USDT-SWAP", None, {}, {}, "cfg_test")
    aid = store.save_analysis(
        ts=ts,
        snapshot_id=sid,
        symbol="BTC-USDT-SWAP",
        score=70,
        direction="bullish",
        plan={"valid": True},
        llm_output=None,
        card_text=None,
        prompt_version="p1",
        config_version="cfg_test",
    )
    store.save_signal(
        ts=ts,
        snapshot_id=sid,
        module=module,
        direction="bullish",
        strength=3,
        confidence="medium",
        details={},
    )
    store.settle_analysis(
        aid,
        outcome=outcome,
        entry_hit=1 if note else 0,
        exit_reason="tp_hit" if outcome == "correct" else "sl_hit",
        settled_ts=ts + 3600,
        outcome_note=note,
    )


def _by_module(report, module):
    return next(a for a in report["advice"] if a["module"] == module)


def test_weight_report_sample_gate_holds(tmp_path):
    s = _store(tmp_path)
    _settled_with_signal(s, ts=1000, module="structure",
                         outcome="wrong", note="pnl_net=-1.000%")

    report = weight_report(s, _Cfg(), days=None)
    advice = _by_module(report, "structure")

    assert advice["entered"] == 1
    assert advice["action"] == "hold"
    assert advice["reason"] == "sample_gate"
    assert advice["current_weight"] == advice["suggested_weight"]
    assert "applied=false" in render_weight_report(report)
    s.close()


def test_weight_report_decreases_after_gate(tmp_path):
    s = _store(tmp_path)
    for i in range(3):
        _settled_with_signal(s, ts=1000 + i, module="volume",
                             outcome="wrong", note="pnl_net=-1.000%")

    report = weight_report(s, _Cfg(), days=None, min_samples=2)
    advice = _by_module(report, "volume")

    assert advice["entered"] == 3
    assert advice["win_rate"] == pytest.approx(0.0)
    assert advice["ev_pct"] == pytest.approx(-1.0)
    assert advice["action"] == "decrease"
    assert advice["reason"] == "underperforming"
    assert advice["suggested_weight"] == pytest.approx(1.8)
    s.close()
