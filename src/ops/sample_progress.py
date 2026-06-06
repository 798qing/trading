"""阶段3采样进度巡检。

只读 analyses，用当前 config_version 口径回答：
- 当前是否只是在等市场给到达阈值的方向性样本；
- 是否有到期未结算导致进度停滞；
- 离 auto-weight 样本门槛还差多少。
"""
from __future__ import annotations

import json
from typing import Any

from common import clock


def _safe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value or not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _fmt_ts(ts: int | None, tz: str) -> str:
    if ts is None:
        return "-"
    return clock.to_local(int(ts), tz).strftime("%Y-%m-%d %H:%M")


def _count(store, sql: str, params: list[Any]) -> int:
    return int(store.conn.execute(sql, params).fetchone()[0])


def _analysis_rows(store, *, symbol: str, config_version: str,
                   since_ts: int | None) -> list:
    where = ["symbol=?", "config_version=?"]
    params: list[Any] = [symbol, config_version]
    if since_ts is not None:
        where.append("ts>=?")
        params.append(since_ts)
    return store.conn.execute(
        "SELECT id,ts,snapshot_id,score,direction,plan,outcome,entry_hit,"
        "exit_reason,settled_ts,config_version "
        "FROM analyses WHERE " + " AND ".join(where) + " ORDER BY ts ASC",
        params,
    ).fetchall()


def _is_directional(row) -> bool:
    return row["direction"] in {"bullish", "bearish"}


def _is_entered_outcome(outcome: str | None) -> bool:
    return outcome in {"correct", "wrong", "partial"}


def _is_valid_trade_plan(plan: dict[str, Any]) -> bool:
    return plan.get("valid") is True and plan.get("direction") in {"long", "short"}


def sample_progress_report(store, cfg, *, days: int | None = 30,
                           now: int | None = None) -> dict:
    """返回当前配置版本下的采样进度，不写库、不触发采集。"""
    symbol = cfg.require("meta.symbol")
    n = clock.now_ts() if now is None else now
    since = None if days is None else n - days * 86400
    config_version = getattr(cfg, "version", "unknown")
    sample_min = cfg.get("plan_builder.backtest_sample_min_score", 40)
    standard_score = cfg.get("scoring.standard_card_score", 60)
    gate = int(cfg.get("ops.auto_weight.min_settled_signals", 30))
    primary = cfg.require("timeframes.primary")
    ttl = int(cfg.get("plan_builder.signal_ttl_klines", 4))
    settle_cutoff = n - (ttl + 1) * clock.tf_seconds(primary)

    rows = _analysis_rows(
        store, symbol=symbol, config_version=config_version, since_ts=since,
    )
    plans = [_safe_json(row["plan"]) for row in rows]

    score_qualified = [
        row for row in rows
        if _is_directional(row)
        and row["score"] is not None
        and row["score"] >= sample_min
    ]
    valid_sample_plan_indexes = [
        i for i, row in enumerate(rows)
        if row["score"] is not None
        and sample_min <= row["score"] < standard_score
        and _is_valid_trade_plan(plans[i])
    ]
    settled_sample_plan_indexes = [
        i for i in valid_sample_plan_indexes if rows[i]["outcome"] is not None
    ]
    entered_sample_plan_indexes = [
        i for i in settled_sample_plan_indexes
        if _is_entered_outcome(rows[i]["outcome"])
    ]

    where = ["symbol=?"]
    params: list[Any] = [symbol]
    if since is not None:
        where.append("ts>=?")
        params.append(since)
    total_window = _count(
        store,
        "SELECT COUNT(*) FROM analyses WHERE " + " AND ".join(where),
        params,
    )

    due_unsettled = [
        row for row in rows if row["outcome"] is None and row["ts"] <= settle_cutoff
    ]
    pending = [row for row in rows if row["outcome"] is None]
    settled = [row for row in rows if row["outcome"] is not None]
    entered_all = [row for row in settled if _is_entered_outcome(row["outcome"])]
    latest = rows[-1] if rows else None
    latest_plan = _safe_json(latest["plan"]) if latest else {}

    remaining = max(0, gate - len(entered_sample_plan_indexes))
    if due_unsettled:
        status = "settlement_backlog"
        reason = "存在到期未结算分析，先等/触发预采集结算"
    elif len(entered_sample_plan_indexes) >= gate:
        status = "ready_for_weight_review"
        reason = "采样门槛已满足，可进入权重复盘"
    elif not score_qualified:
        status = "waiting_for_market"
        reason = "当前配置版本下还没有达到采样阈值的方向性观望样本"
    elif not valid_sample_plan_indexes:
        status = "waiting_for_valid_plan"
        reason = "已有方向性高分候选，但尚未形成有效纸面计划"
    else:
        status = "collecting_samples"
        reason = "纸面计划已生成，等待成交/结算样本累计"

    return {
        "symbol": symbol,
        "days": days,
        "config_version": config_version,
        "now": n,
        "thresholds": {
            "sample_min_score": sample_min,
            "standard_card_score": standard_score,
            "auto_weight_min_samples": gate,
        },
        "counts": {
            "total_analyses_window": total_window,
            "current_config_analyses": len(rows),
            "pending_current_config": len(pending),
            "settled_current_config": len(settled),
            "due_unsettled_current_config": len(due_unsettled),
            "score_qualified_directional": len(score_qualified),
            "valid_sample_plans": len(valid_sample_plan_indexes),
            "settled_sample_plans": len(settled_sample_plan_indexes),
            "entered_sample_plans": len(entered_sample_plan_indexes),
            "entered_all_current_config": len(entered_all),
            "remaining_to_gate": remaining,
        },
        "latest": None if latest is None else {
            "id": int(latest["id"]),
            "ts": int(latest["ts"]),
            "snapshot_id": latest["snapshot_id"],
            "score": latest["score"],
            "direction": latest["direction"],
            "plan_valid": latest_plan.get("valid"),
            "plan_direction": latest_plan.get("direction"),
            "outcome": latest["outcome"] or "pending",
            "settled_ts": latest["settled_ts"],
        },
        "status": status,
        "reason": reason,
    }


def render_sample_progress(report: dict, *, timezone: str = "Asia/Shanghai") -> str:
    title_days = "all" if report["days"] is None else f"{report['days']}d"
    c = report["counts"]
    t = report["thresholds"]
    lines = [
        f"采样进度 {report['symbol']} ({title_days}) status={report['status']}",
        f"config={report['config_version']} reason={report['reason']}",
        (
            f"thresholds: sample_score>={t['sample_min_score']} "
            f"standard_score={t['standard_card_score']} "
            f"auto_weight_gate={t['auto_weight_min_samples']}"
        ),
        (
            f"analyses: total_window={c['total_analyses_window']} "
            f"current_cfg={c['current_config_analyses']} "
            f"pending={c['pending_current_config']} "
            f"settled={c['settled_current_config']} "
            f"due={c['due_unsettled_current_config']}"
        ),
        (
            f"samples: score_qualified={c['score_qualified_directional']} "
            f"valid_plans={c['valid_sample_plans']} "
            f"settled_plans={c['settled_sample_plans']} "
            f"entered={c['entered_sample_plans']} "
            f"remaining={c['remaining_to_gate']}"
        ),
    ]
    latest = report["latest"]
    if latest:
        lines.append(
            f"latest: #{latest['id']} {_fmt_ts(latest['ts'], timezone)} "
            f"score={latest['score'] if latest['score'] is not None else '-'} "
            f"dir={latest['direction'] or '-'} "
            f"plan={latest['plan_direction'] or '-'} "
            f"valid={latest['plan_valid']} outcome={latest['outcome']}"
        )
    else:
        lines.append("latest: -")
    return "\n".join(lines)


def sample_progress_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
