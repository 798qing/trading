"""analyze.py — 流水线编排 + 大周期判向接线 + 落库。"""
import textwrap

import pytest

from analyze import analyze, persist
from common import clock
from common.config import load_config
from data.snapshot import build_snapshot
from data.store import Store


def _cfg(tmp_path, tfs='["15m"]', higher="[]"):
    body = f"""
    meta: {{label: t, symbol: BTC-USDT-SWAP}}
    timeframes: {{all: {tfs}, primary: "15m", higher: {higher}, min_klines: 300}}
    scoring: {{push_threshold: 65, standard_card_score: 60, conflict_score_cap: 55}}
    plan_builder: {{entry_max_deviation_pct: 2.0, stop_min_pct: 0.5, stop_max_pct: 5.0,
                   min_risk_reward: 1.5, atr_period: 14, signal_ttl_klines: 4}}
    hard_constraints:
      structural_veto: {{higher_tf_opposite: true, breakout_low_volume: true}}
      contextual_veto: {{adx_min: 18}}
    fusion:
      base_weights: {{structure: 1.5, volume: 2.0, adx: 0.5, fib: 0.8}}
      trend_multiplier: {{with_trend: 1.5, against_trend: 0.5}}
      data_quality_multiplier: {{exact: 1.0, approximated: 0.7, stale: 0.3, unavailable: 0.0}}
      trend_multiplier_exempt: [wyckoff]
      exempt_events: [Spring]
    display: {{timezone: UTC}}
    ops: {{db_path: data/t.db}}
    """
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return load_config(p)


def _seed(store, tf, now, n=80, base=100.0):
    lc = clock.last_closed_ts(tf, now=now)
    sec = clock.tf_seconds(tf)
    rows = [(lc - i * sec, base + i, base + i + 0.5, base + i - 0.5, base + i, 1000.0)
            for i in range(n)]
    store.upsert_klines(tf, rows)


def _aux(now):
    return {"mark": {"price": 100.0, "as_of_ts": now},
            "funding": {"rate": 0.0001, "next_funding_ts": now + 3600, "as_of_ts": now},
            "oi": {"oi": 1000.0, "oi_ccy": 10.0, "as_of_ts": now}}


def test_analyze_runs_and_persists(tmp_path):
    cfg = _cfg(tmp_path)
    store = Store(tmp_path / "t.db"); store.init_db()
    now = 1_780_000_000
    _seed(store, "15m", now, n=80)
    snap = build_snapshot(store, cfg, _aux(now), now=now, persist=True)

    a = analyze(store, cfg, snapshot=snap)
    assert a.recommendation in {"signal", "wait"}
    assert set(a.signals) == {"structure", "volume", "adx", "fib",
                              "candle", "macd", "rsi", "wyckoff"}

    aid = persist(store, cfg, a)
    assert aid > 0
    row = dict(store.conn.execute("SELECT * FROM analyses WHERE id=?", (aid,)).fetchone())
    assert row["config_version"] == cfg.version
    n_sig = store.conn.execute(
        "SELECT COUNT(*) FROM signals WHERE snapshot_id=?", (snap.snapshot_id,)
    ).fetchone()[0]
    assert n_sig == 8
    store.close()


def test_analyze_replay_is_deterministic(tmp_path):
    # 阶段1验收：同一冻结快照重跑，检测/聚合/计划输出完全一致（D6 可重放）
    cfg = _cfg(tmp_path)
    store = Store(tmp_path / "t.db"); store.init_db()
    now = 1_780_000_000
    _seed(store, "15m", now, n=80)
    snap = build_snapshot(store, cfg, _aux(now), now=now, persist=False)
    a1 = analyze(store, cfg, snapshot=snap)
    a2 = analyze(store, cfg, snapshot=snap)
    assert a1.fusion.score == a2.fusion.score
    assert a1.fusion.direction == a2.fusion.direction
    assert a1.plan.to_dict() == a2.plan.to_dict()
    assert a1.recommendation == a2.recommendation
    store.close()


def test_htf_direction_wired_into_fusion(tmp_path):
    cfg = _cfg(tmp_path, tfs='["15m","4h"]', higher='["4h"]')
    store = Store(tmp_path / "t.db"); store.init_db()
    now = 1_780_000_000
    _seed(store, "15m", now, n=80)
    _seed(store, "4h", now, n=80)               # 大周期也有数据
    snap = build_snapshot(store, cfg, _aux(now), now=now, persist=False)
    a = analyze(store, cfg, snapshot=snap)
    # 大周期方向已算入 fusion 的 timeframe_alignment（接线生效）
    assert "4h" in a.fusion.timeframe_alignment
    assert a.fusion.timeframe_alignment["4h"] in {"bullish", "bearish", "neutral"}
    store.close()
