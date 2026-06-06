"""metrics.py — 阶段3 回测统计（胜率/EV/MDD/Sortino + 版本分组）。"""
import pytest

from backtest.metrics import compute_metrics, grouped_metrics, metrics_report, render_report
from data.store import Store


class _Cfg:
    def require(self, dotted):
        if dotted == "meta.symbol":
            return "BTC-USDT-SWAP"
        raise KeyError(dotted)


def _store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.init_db()
    return s


def _snapshot_id(ts=1000, prompt="p1", cfg="cfg_a"):
    return f"snap-{ts}-{prompt}-{cfg}"


def _analysis(store, *, ts=1000, prompt="p1", cfg="cfg_a", market_state=None):
    sid = f"snap-{ts}-{prompt}-{cfg}"
    store.save_snapshot(sid, ts, "BTC-USDT-SWAP", market_state, {}, {}, cfg)
    return store.save_analysis(
        ts=ts, snapshot_id=sid, symbol="BTC-USDT-SWAP", score=70,
        direction="bullish", plan={"valid": True}, llm_output=None,
        card_text=None, prompt_version=prompt, config_version=cfg,
    )


def _settled_rows(store):
    return store.settled_analyses(symbol="BTC-USDT-SWAP")


def test_compute_metrics_core_numbers(tmp_path):
    s = _store(tmp_path)
    cases = [
        ("correct", "tp_hit", "pnl_net=2.000%"),
        ("wrong", "sl_hit", "pnl_net=-1.000%"),
        ("partial", "expired", "pnl_net=0.500%"),
        ("expired", "expired", None),
        ("no_trade", "no_signal", None),
    ]
    for i, (outcome, exit_reason, note) in enumerate(cases):
        aid = _analysis(s, ts=1000 + i)
        s.settle_analysis(aid, outcome=outcome, entry_hit=int(note is not None),
                          exit_reason=exit_reason, settled_ts=2000, outcome_note=note)

    m = compute_metrics(_settled_rows(s))

    assert m.total == 5
    assert m.entered == 3
    assert m.wins == 1 and m.losses == 1 and m.partials == 1
    assert m.expired == 1 and m.no_trade == 1
    assert m.win_rate == pytest.approx(1 / 3)
    assert m.ev_pct == pytest.approx(0.5)
    assert m.total_return_pct == pytest.approx(1.4849)
    assert m.max_drawdown_pct == pytest.approx(1.0)
    assert m.sortino == pytest.approx(0.8660254)
    s.close()


def test_grouped_metrics_by_prompt_and_config(tmp_path):
    s = _store(tmp_path)
    aid1 = _analysis(s, ts=1000, prompt="p1", cfg="cfg_a")
    aid2 = _analysis(s, ts=2000, prompt="p2", cfg="cfg_b")
    s.settle_analysis(aid1, outcome="correct", entry_hit=1, exit_reason="tp_hit",
                      settled_ts=3000, outcome_note="pnl_net=1.000%")
    s.settle_analysis(aid2, outcome="wrong", entry_hit=1, exit_reason="sl_hit",
                      settled_ts=3000, outcome_note="pnl_net=-1.000%")

    groups = grouped_metrics(_settled_rows(s))

    assert [(g.prompt_version, g.config_version, g.entered) for g in groups] == [
        ("p1", "cfg_a", 1),
        ("p2", "cfg_b", 1),
    ]
    s.close()


def test_metrics_report_filters_days_and_renders_empty(tmp_path):
    s = _store(tmp_path)
    now = 10 * 86400
    old = _analysis(s, ts=1, prompt="p1", cfg="cfg_a")
    fresh = _analysis(s, ts=now - 3600, prompt="p1", cfg="cfg_a")
    s.settle_analysis(old, outcome="correct", entry_hit=1, exit_reason="tp_hit",
                      settled_ts=now, outcome_note="pnl_net=9.000%")
    s.settle_analysis(fresh, outcome="wrong", entry_hit=1, exit_reason="sl_hit",
                      settled_ts=now, outcome_note="pnl_net=-2.000%")

    report = metrics_report(s, _Cfg(), days=1, now=now)

    assert report["overall"]["total"] == 1
    assert report["overall"]["ev_pct"] == pytest.approx(-2.0)
    assert "回测统计 BTC-USDT-SWAP (1d)" in render_report(report)

    empty = metrics_report(s, _Cfg(), days=0, now=now)
    assert empty["overall"]["prompt_version"] == "none"
    assert "total=0" in render_report(empty)
    s.close()


def test_metrics_report_groups_by_market_regime(tmp_path):
    s = _store(tmp_path)
    trend = _analysis(s, ts=1000)
    range_ = _analysis(s, ts=2000)
    transition = _analysis(s, ts=3000)

    s.save_signal(
        ts=1000,
        snapshot_id=_snapshot_id(1000),
        module="adx",
        direction="neutral",
        strength=5,
        confidence="high",
        details={"classification": "strong"},
    )
    s.save_signal(
        ts=1000,
        snapshot_id=_snapshot_id(1000),
        module="structure",
        direction="bullish",
        strength=4,
        confidence="high",
        details={"structure": "uptrend"},
    )
    s.save_signal(
        ts=2000,
        snapshot_id=_snapshot_id(2000),
        module="adx",
        direction="neutral",
        strength=1,
        confidence="high",
        details={"classification": "no_trend"},
    )
    s.save_signal(
        ts=3000,
        snapshot_id=_snapshot_id(3000),
        module="vol_regime",
        direction="neutral",
        strength=5,
        confidence="high",
        details={"regime": "high_vol"},
    )
    s.save_signal(
        ts=3000,
        snapshot_id=_snapshot_id(3000),
        module="structure",
        direction="bearish",
        strength=4,
        confidence="high",
        details={"structure": "range"},
    )
    s.save_signal(
        ts=3000,
        snapshot_id=_snapshot_id(3000),
        module="macd",
        direction="bullish",
        strength=4,
        confidence="medium",
        details={},
    )

    s.settle_analysis(trend, outcome="correct", entry_hit=1, exit_reason="tp_hit",
                      settled_ts=4000, outcome_note="pnl_net=2.000%")
    s.settle_analysis(range_, outcome="wrong", entry_hit=1, exit_reason="sl_hit",
                      settled_ts=4000, outcome_note="pnl_net=-1.000%")
    s.settle_analysis(transition, outcome="partial", entry_hit=1,
                      exit_reason="expired", settled_ts=4000,
                      outcome_note="pnl_net=0.500%")

    report = metrics_report(s, _Cfg(), days=None)
    regimes = {r["market_regime"]: r for r in report["regimes"]}

    assert list(regimes) == ["trend", "range", "transition"]
    assert regimes["trend"]["wins"] == 1
    assert regimes["range"]["losses"] == 1
    assert regimes["transition"]["partials"] == 1

    rendered = render_report(report)
    assert "by regime:" in rendered
    assert "趋势(trend)" in rendered
    assert "震荡(range)" in rendered
    assert "过渡(transition)" in rendered
    s.close()
