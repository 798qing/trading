"""结算闭环（P0-1 判定 + P0-2 job）。

按 specs/trade_lifecycle.md 对已了结信号回填 outcome/entry_hit/exit_reason/pnl。
judge_outcome 为纯函数（可离线测）；settle_due 是每 15m 收线后跑的扫描 job。
"""
from __future__ import annotations

import json
from collections import namedtuple
from dataclasses import dataclass

from common import clock

# 重放用的轻量 K 线视图（judge_outcome 用属性访问 .high/.low/.close）
_Bar = namedtuple("_Bar", "high low close")


@dataclass
class Outcome:
    outcome: str          # correct/wrong/partial/expired/no_trade
    entry_hit: int        # 0/1
    exit_reason: str      # tp_hit/sl_hit/expired/no_signal
    pnl_net_pct: float | None = None

    @property
    def note(self) -> str:
        if self.pnl_net_pct is None:
            return ""
        return f"pnl_net={self.pnl_net_pct:.3f}%"


def _costs_pct(cfg, holding_intervals: int, funding_rate: float) -> float:
    """双边手续费 + 双边滑点 + 资金费率×持有结算次数（百分比，正=成本）。"""
    c = cfg.get("costs", {})
    taker = c.get("fee_taker_pct", 0.05)
    slip = c.get("slippage_pct", 0.05)
    fee = 2 * taker + 2 * slip
    funding = abs(funding_rate) * 100 * max(0, holding_intervals)
    return fee + funding


def judge_outcome(plan: dict, klines: list, cfg, funding_rate: float = 0.0) -> Outcome:
    """对一条计划重放窗口内 K 线，判定 outcome（specs/trade_lifecycle.md）。

    klines：analysis_ts 之后的已收线 K 线（升序），最多 signal_ttl_klines 根。
    每根需有 .high/.low/.close 属性。
    """
    if not plan or not plan.get("valid") or plan.get("direction") not in ("long", "short"):
        return Outcome("no_trade", 0, "no_signal", None)

    direction = plan["direction"]
    entry_lo, entry_hi = plan["entry_zone"]
    entry_ref = (entry_lo + entry_hi) / 2
    stop = plan["stop_loss"]
    tp1 = plan["targets"][0]
    is_long = direction == "long"

    funding_interval_h = cfg.get("costs.funding_interval_hours", 8)
    tf = cfg.require("timeframes.primary")
    tf_h = clock.tf_seconds(tf) / 3600

    entered = False
    for i, k in enumerate(klines):
        if not entered:
            if k.low <= entry_hi and k.high >= entry_lo:   # 入场区被触及
                entered = True
        if entered:
            if is_long:
                tp_hit, sl_hit = k.high >= tp1, k.low <= stop
            else:
                tp_hit, sl_hit = k.low <= tp1, k.high >= stop
            holding = max(1, int((i + 1) * tf_h / funding_interval_h))
            if sl_hit:                       # 含同根 SL+TP → 最不利取 SL
                pnl = _pnl(direction, entry_ref, stop, cfg, holding, funding_rate)
                return Outcome("wrong", 1, "sl_hit", pnl)
            if tp_hit:
                pnl = _pnl(direction, entry_ref, tp1, cfg, holding, funding_rate)
                return Outcome("correct", 1, "tp_hit", pnl)

    if not entered:
        return Outcome("expired", 0, "expired", None)     # 未成交，不计入分母

    # 在场到期：按末根 close 的净盈亏方向判 partial
    holding = max(1, int(len(klines) * tf_h / funding_interval_h))
    pnl = _pnl(direction, entry_ref, klines[-1].close, cfg, holding, funding_rate)
    return Outcome("partial", 1, "expired", pnl)


def _pnl(direction: str, entry: float, exit_: float, cfg, holding: int,
         funding_rate: float) -> float:
    raw = (exit_ - entry) / entry * 100
    if direction == "short":
        raw = -raw
    return raw - _costs_pct(cfg, holding, funding_rate)


def settle_due(store, cfg, now: int | None = None) -> int:
    """扫描有效期已过、未结算的信号，回填 outcome（P0-2）。返回结算条数。"""
    n = clock.now_ts() if now is None else now
    primary = cfg.require("timeframes.primary")
    ttl = cfg.get("plan_builder.signal_ttl_klines", 4)
    tf_sec = clock.tf_seconds(primary)
    # 有效期 + 一根缓冲都过了才结算
    cutoff = n - (ttl + 1) * tf_sec

    settled = 0
    for row in store.unsettled_analyses(before_ts=cutoff):
        d = dict(row)
        plan = json.loads(d["plan"]) if d.get("plan") else None
        window = [_Bar(r["high"], r["low"], r["close"])
                  for r in store.klines_after(primary, d["ts"], limit=ttl)]
        funding = _row_funding(store, d["snapshot_id"])
        oc = judge_outcome(plan, window, cfg, funding_rate=funding)
        store.settle_analysis(d["id"], outcome=oc.outcome, entry_hit=oc.entry_hit,
                              exit_reason=oc.exit_reason, settled_ts=n,
                              outcome_note=oc.note or None)
        settled += 1
    return settled


def _row_funding(store, snapshot_id: str) -> float:
    """取该快照记录的资金费率（用于成本估算），缺失视为 0。"""
    snap = store.get_snapshot(snapshot_id)
    if not snap:
        return 0.0
    return (snap.get("payload", {}).get("sources", {}).get("funding") or {}).get("rate", 0.0) or 0.0
