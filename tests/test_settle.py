"""settle.py — outcome 判定（P0-1）+ 结算 job（P0-2）。"""
import textwrap
from collections import namedtuple

import pytest

from backtest.settle import judge_outcome, settle_due
from common.config import load_config
from data.store import Store

K = namedtuple("K", "high low close")

_CFG = """
meta: {label: t, symbol: BTC-USDT-SWAP}
timeframes: {all: ["15m"], primary: "15m", higher: [], min_klines: 300}
scoring: {push_threshold: 65, standard_card_score: 60, conflict_score_cap: 55}
plan_builder: {stop_min_pct: 0.5, stop_max_pct: 5.0, min_risk_reward: 1.5, signal_ttl_klines: 4}
costs: {fee_taker_pct: 0.05, slippage_pct: 0.05, funding_interval_hours: 8}
hard_constraints: {contextual_veto: {adx_min: 18}}
display: {timezone: UTC}
ops: {db_path: data/t.db}
"""


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent(_CFG), encoding="utf-8")
    return load_config(p)


_LONG = {"valid": True, "direction": "long", "entry_zone": [99.0, 100.0],
         "stop_loss": 97.0, "targets": [104.0, 107.0]}


def test_correct_tp_before_sl(cfg):
    win = [K(100, 98, 99.5), K(105, 100, 104.5)]   # 入场→TP
    o = judge_outcome(_LONG, win, cfg)
    assert o.outcome == "correct" and o.entry_hit == 1 and o.exit_reason == "tp_hit"


def test_wrong_sl_before_tp(cfg):
    win = [K(100, 98, 99.5), K(100, 96, 96.5)]     # 入场→SL
    o = judge_outcome(_LONG, win, cfg)
    assert o.outcome == "wrong" and o.exit_reason == "sl_hit"


def test_same_candle_sl_and_tp_is_wrong(cfg):
    win = [K(100, 98, 99.5), K(105, 96, 100)]      # 同根触及 TP 与 SL → 最不利取 SL
    o = judge_outcome(_LONG, win, cfg)
    assert o.outcome == "wrong" and o.exit_reason == "sl_hit"


def test_expired_no_entry(cfg):
    win = [K(98, 97.5, 97.8), K(98, 97.6, 97.9)]   # 始终在入场区下方,未触及
    o = judge_outcome(_LONG, win, cfg)
    assert o.outcome == "expired" and o.entry_hit == 0


def test_partial_in_trade_timeout(cfg):
    win = [K(100, 99.5, 99.8), K(101, 99, 100.5)]  # 入场但到期未达 TP/SL
    o = judge_outcome(_LONG, win, cfg)
    assert o.outcome == "partial" and o.entry_hit == 1 and o.exit_reason == "expired"
    assert o.pnl_net_pct is not None


def test_no_trade_invalid_plan(cfg):
    o = judge_outcome({"valid": False, "direction": "none"}, [], cfg)
    assert o.outcome == "no_trade" and o.exit_reason == "no_signal"


def test_costs_make_breakeven_negative(cfg):
    # 出场=入场(0 毛利) → 扣双边手续费+滑点 → 净为负
    win = [K(100, 99.5, 99.5)]                     # 入场即末根, close=entry_ref 附近
    o = judge_outcome(_LONG, win, cfg)
    assert o.pnl_net_pct < 0


def test_settle_due_backfills_and_clears(cfg, tmp_path):
    store = Store(tmp_path / "t.db"); store.init_db()
    ats = 1_780_000_000
    store.save_snapshot("snap1", ats, "BTC-USDT-SWAP", None, {}, {}, cfg.version)
    aid = store.save_analysis(ts=ats, snapshot_id="snap1", symbol="BTC-USDT-SWAP",
                              score=72, direction="bullish", plan=_LONG, llm_output=None,
                              card_text=None, prompt_version=None,
                              config_version=cfg.version)
    # analysis_ts 之后种入会触及 TP 的 K 线
    store.upsert_klines("15m", [(ats + 900, 100, 100, 98, 99.5, 1.0),
                                (ats + 1800, 105, 105, 100, 104.5, 1.0)])
    now = ats + 10 * 900                            # 有效期早已过
    n = settle_due(store, cfg, now=now)
    assert n == 1
    row = dict(store.conn.execute("SELECT * FROM analyses WHERE id=?", (aid,)).fetchone())
    assert row["outcome"] == "correct" and row["entry_hit"] == 1
    assert row["settled_ts"] == now
    # 已结算 → 不再出现在未结算扫描
    assert store.unsettled_analyses(before_ts=now) == []
    store.close()
