"""snapshot.py — 冻结、防前视边界、data_quality（D6/D7/P0-4）。离线，不联网。"""
import textwrap

import pytest

from common import clock
from common.config import load_config
from data.snapshot import build_snapshot, latest_sources
from data.store import Store

_CFG = """
meta: {label: t, symbol: BTC-USDT-SWAP}
timeframes: {all: ["15m"], primary: "15m", higher: [], min_klines: 60}
scoring: {push_threshold: 65, standard_card_score: 60, conflict_score_cap: 55}
plan_builder: {stop_min_pct: 0.5, stop_max_pct: 5.0, min_risk_reward: 1.5}
hard_constraints: {contextual_veto: {adx_min: 18}}
display: {timezone: UTC}
ops: {db_path: data/t.db}
"""


def _setup(tmp_path, n_klines=60):
    cfg = load_config(_write(tmp_path, _CFG))
    store = Store(tmp_path / "t.db")
    store.init_db()
    now = 1_780_000_000
    lc = clock.last_closed_ts("15m", now=now)          # 最近已收线开盘 ts
    # 已收线序列：lc, lc-900, ...（升序种入）
    closed = [(lc - i * 900, 100 + i, 110 + i, 90 + i, 105 + i, 1000.0)
              for i in range(n_klines)]
    store.upsert_klines("15m", closed)
    # 再种 2 根“未来/未收线”：当前形成中那根 + 下一根 —— 必须被裁掉
    forming = clock.floor_ts(now, "15m")
    store.upsert_klines("15m", [(forming, 1, 1, 1, 1, 1),
                                (forming + 900, 2, 2, 2, 2, 2)])
    return cfg, store, now, lc


def _write(tmp_path, body):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def _aux(now, mark_as_of=None):
    return {
        "mark": {"price": 67000.0, "as_of_ts": mark_as_of if mark_as_of else now},
        "funding": {"rate": 0.0001, "next_funding_ts": now + 3600, "as_of_ts": now},
        "oi": {"oi": 123.0, "oi_ccy": 1.0, "as_of_ts": now},
    }


def test_freeze_excludes_unclosed_and_sets_analysis_ts(tmp_path):
    cfg, store, now, lc = _setup(tmp_path)
    snap = build_snapshot(store, cfg, _aux(now), now=now)
    assert snap.analysis_ts == lc
    ks = snap.klines("15m")
    # 未收线/未来两根被裁掉；最后一根恰为 last_closed
    assert ks[-1].ts == lc
    assert all(k.ts <= lc for k in ks)


def test_snapshot_id_format(tmp_path):
    cfg, store, now, lc = _setup(tmp_path)
    snap = build_snapshot(store, cfg, _aux(now), now=now)
    assert snap.snapshot_id.startswith("btc_")
    assert len(snap.snapshot_id.split("_")) == 3   # btc_YYYYMMDD_HHMMSS


def test_persisted_and_carries_config_version(tmp_path):
    cfg, store, now, lc = _setup(tmp_path)
    snap = build_snapshot(store, cfg, _aux(now), now=now)
    saved = store.get_snapshot(snap.snapshot_id)
    assert saved is not None
    assert saved["config_version"] == cfg.version
    assert snap.config_version == cfg.version


def test_data_quality_complete_when_enough_and_fresh(tmp_path):
    cfg, store, now, lc = _setup(tmp_path, n_klines=60)
    snap = build_snapshot(store, cfg, _aux(now), now=now)
    assert snap.data_quality["is_complete"] is True
    assert snap.data_quality["has_stale_source"] is False


def test_insufficient_rows_flags_incomplete(tmp_path):
    cfg, store, now, lc = _setup(tmp_path, n_klines=10)
    snap = build_snapshot(store, cfg, _aux(now), now=now)
    assert snap.data_quality["is_complete"] is False
    assert any("不足" in w for w in snap.data_quality["warnings"])


def test_stale_mark_detected(tmp_path):
    cfg, store, now, lc = _setup(tmp_path)
    snap = build_snapshot(store, cfg, _aux(now, mark_as_of=now - 9999), now=now)
    assert snap.sources["mark"]["status"] == "stale"
    assert snap.data_quality["has_stale_source"] is True


def test_unavailable_mark_breaks_completeness(tmp_path):
    cfg, store, now, lc = _setup(tmp_path)
    aux = _aux(now)
    aux["mark"] = None
    snap = build_snapshot(store, cfg, aux, now=now)
    assert snap.sources["mark"]["status"] == "unavailable"
    assert snap.data_quality["is_complete"] is False


def test_latest_sources_carries_optional_spot(tmp_path):
    cfg, store, now, lc = _setup(tmp_path)
    aux = _aux(now)
    aux["spot"] = {"price": 66950.0, "as_of_ts": now}

    build_snapshot(store, cfg, aux, now=now)

    sources = latest_sources(store)
    assert sources["spot"]["price"] == 66950.0


def test_snapshot_carries_stage3_optional_sources(tmp_path):
    cfg, store, now, lc = _setup(tmp_path)
    aux = _aux(now)
    aux["long_short"] = {"long_ratio": 0.6, "short_ratio": 0.4,
                         "long_short_ratio": 1.5, "as_of_ts": now}
    aux["etf_flow"] = {"ticker": "IBIT", "net_flow_usd": 1_000_000.0,
                       "as_of_ts": now}
    aux["exchange_netflow"] = {"netflow_total": -123.0, "as_of_ts": now}
    aux["macro"] = {"risk_state": "risk_on", "event_in_window": False,
                    "as_of_ts": now}

    build_snapshot(store, cfg, aux, now=now)

    sources = latest_sources(store)
    assert sources["long_short"]["long_short_ratio"] == 1.5
    assert sources["etf_flow"]["net_flow_usd"] == 1_000_000.0
    assert sources["exchange_netflow"]["netflow_total"] == -123.0
    assert sources["macro"]["risk_state"] == "risk_on"
