"""历史查询：最近分析/结算流水。

给 CLI/Hermes 查询用，只读 analyses，不触发 live 采集、不改状态。
"""
from __future__ import annotations

import json
from typing import Any

from backtest.metrics import pnl_from_note
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


def history_report(store, cfg, *, days: int | None = 30, limit: int = 10,
                   outcome: str | None = None, now: int | None = None) -> dict:
    """返回最近 analyses 流水；outcome='pending' 表示未结算。"""
    symbol = cfg.require("meta.symbol")
    n = clock.now_ts() if now is None else now
    since = None if days is None else n - days * 86400
    limit = max(1, min(int(limit), 100))

    where = ["symbol=?"]
    params: list[Any] = [symbol]
    if since is not None:
        where.append("ts>=?")
        params.append(since)
    if outcome == "pending":
        where.append("outcome IS NULL")
    elif outcome:
        where.append("outcome=?")
        params.append(outcome)

    where_sql = " AND ".join(where)
    total = int(store.conn.execute(
        f"SELECT COUNT(*) FROM analyses WHERE {where_sql}",
        params,
    ).fetchone()[0])
    rows = store.conn.execute(
        "SELECT id,ts,snapshot_id,symbol,score,direction,plan,prompt_version,"
        "config_version,outcome,outcome_note,entry_hit,exit_reason,settled_ts "
        f"FROM analyses WHERE {where_sql} ORDER BY ts DESC LIMIT ?",
        [*params, limit],
    ).fetchall()

    items = []
    for row in rows:
        plan = _safe_json(row["plan"])
        items.append({
            "id": int(row["id"]),
            "ts": int(row["ts"]),
            "snapshot_id": row["snapshot_id"],
            "symbol": row["symbol"],
            "score": row["score"],
            "direction": row["direction"],
            "plan_direction": plan.get("direction"),
            "plan_valid": plan.get("valid"),
            "entry_zone": plan.get("entry_zone"),
            "stop_loss": plan.get("stop_loss"),
            "targets": plan.get("targets"),
            "risk_reward": plan.get("risk_reward"),
            "prompt_version": row["prompt_version"] or "unknown",
            "config_version": row["config_version"] or "unknown",
            "outcome": row["outcome"] or "pending",
            "entry_hit": row["entry_hit"],
            "exit_reason": row["exit_reason"],
            "settled_ts": row["settled_ts"],
            "pnl_net_pct": pnl_from_note(row["outcome_note"]),
        })

    return {
        "symbol": symbol,
        "days": days,
        "limit": limit,
        "outcome": outcome or "all",
        "total_matches": total,
        "items": items,
    }


def render_history(report: dict, *, timezone: str = "Asia/Shanghai") -> str:
    title_days = "all" if report["days"] is None else f"{report['days']}d"
    lines = [
        (
            f"历史查询 {report['symbol']} ({title_days}) "
            f"outcome={report['outcome']} total={report['total_matches']} "
            f"limit={report['limit']}"
        )
    ]
    if not report["items"]:
        lines.append("- no records")
        return "\n".join(lines)

    for item in report["items"]:
        pnl = "-" if item["pnl_net_pct"] is None else f"{item['pnl_net_pct']:.2f}%"
        entry = item["entry_zone"] or "-"
        lines.append(
            f"- #{item['id']} {_fmt_ts(item['ts'], timezone)} "
            f"score={item['score'] if item['score'] is not None else '-'} "
            f"dir={item['direction'] or '-'} plan={item['plan_direction'] or '-'} "
            f"outcome={item['outcome']} pnl={pnl} entry={entry} "
            f"cfg={item['config_version']}"
        )
    return "\n".join(lines)


def history_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
