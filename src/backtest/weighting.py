"""阶段3 auto-weight 建议器。

第一版只读已结算 analyses + signals，生成权重调整建议；不直接改配置。
P0-6/D13：样本量不足时只告警，不移动权重。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from backtest.metrics import pnl_from_note
from common import clock


@dataclass(frozen=True)
class WeightAdvice:
    module: str
    current_weight: float
    suggested_weight: float
    total: int
    entered: int
    wins: int
    losses: int
    partials: int
    pnl_samples: int
    win_rate: float | None
    ev_pct: float | None
    action: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _entered(outcome: str | None) -> bool:
    return outcome in {"correct", "wrong", "partial"}


def _compute_advice(module: str, current_weight: float, rows: Iterable,
                    *, min_samples: int) -> WeightAdvice:
    rows = list(rows)
    outcomes = [r["outcome"] for r in rows]
    wins = outcomes.count("correct")
    losses = outcomes.count("wrong")
    partials = outcomes.count("partial")
    entered = sum(1 for o in outcomes if _entered(o))
    pnls = [p for p in (pnl_from_note(r["outcome_note"]) for r in rows)
            if p is not None]
    win_rate = wins / entered if entered else None
    ev_pct = sum(pnls) / len(pnls) if pnls else None

    action = "hold"
    reason = "stable"
    suggested = current_weight
    if entered < min_samples:
        reason = "sample_gate"
    elif (win_rate is not None and win_rate < 0.40) or (
        ev_pct is not None and ev_pct < -0.25
    ):
        action = "decrease"
        reason = "underperforming"
        suggested = round(max(0.0, current_weight * 0.9), 3)
    elif (win_rate is not None and win_rate > 0.58) and (
        ev_pct is not None and ev_pct > 0.25
    ):
        action = "increase"
        reason = "outperforming"
        suggested = round(current_weight * 1.05, 3)

    return WeightAdvice(
        module=module,
        current_weight=float(current_weight),
        suggested_weight=float(suggested),
        total=len(rows),
        entered=entered,
        wins=wins,
        losses=losses,
        partials=partials,
        pnl_samples=len(pnls),
        win_rate=win_rate,
        ev_pct=ev_pct,
        action=action,
        reason=reason,
    )


def _signal_rows(store, cfg, *, since_ts: int | None) -> list:
    where = [
        "a.outcome IS NOT NULL",
        "a.symbol=?",
        "s.direction IN ('bullish','bearish')",
    ]
    params: list[object] = [cfg.require("meta.symbol")]
    if since_ts is not None:
        where.append("a.ts>=?")
        params.append(since_ts)
    query = (
        "SELECT s.module AS module, a.outcome AS outcome, "
        "a.outcome_note AS outcome_note "
        "FROM analyses a JOIN signals s ON s.snapshot_id=a.snapshot_id "
        "WHERE " + " AND ".join(where) + " ORDER BY a.ts ASC"
    )
    return store.conn.execute(query, params).fetchall()


def weight_report(store, cfg, *, days: int | None = 30,
                  min_samples: int | None = None,
                  now: int | None = None) -> dict:
    """返回各 fusion module 的 auto-weight 建议报告。

    报告只建议，不写配置；真正调权重应由人工或后续 apply 子命令完成。
    """
    gate = int(min_samples or cfg.get("ops.auto_weight.min_settled_signals", 30))
    since = None
    if days is not None:
        n = clock.now_ts() if now is None else now
        since = n - days * 86400

    weights = cfg.get("fusion.base_weights", {})
    grouped: dict[str, list] = {m: [] for m in weights}
    for row in _signal_rows(store, cfg, since_ts=since):
        module = row["module"]
        if module in grouped:
            grouped[module].append(row)

    advice = [
        _compute_advice(module, float(weights[module]), grouped[module],
                        min_samples=gate)
        for module in sorted(weights)
    ]
    return {
        "symbol": cfg.require("meta.symbol"),
        "days": days,
        "config_version": cfg.version,
        "min_samples": gate,
        "applied": False,
        "advice": [a.to_dict() for a in advice],
    }


def _pct(v: float | None, digits: int = 1) -> str:
    return "-" if v is None else f"{v:.{digits}f}%"


def render_weight_report(report: dict) -> str:
    title_days = "all" if report["days"] is None else f"{report['days']}d"
    lines = [
        f"自动权重建议 {report['symbol']} ({title_days})",
        (
            f"config={report['config_version']} min_samples={report['min_samples']} "
            "applied=false"
        ),
    ]
    for a in report["advice"]:
        lines.append(
            f"- {a['module']}: action={a['action']} reason={a['reason']} "
            f"n={a['entered']}/{a['total']} win="
            f"{_pct(None if a['win_rate'] is None else a['win_rate'] * 100)} "
            f"EV={_pct(a['ev_pct'])} weight={a['current_weight']:.3f}"
            f"->{a['suggested_weight']:.3f}"
        )
    return "\n".join(lines)
