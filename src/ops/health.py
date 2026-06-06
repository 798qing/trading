"""运行健康检查：数据库、热库新鲜度、结算积压、最近推送。

只读当前 SQLite 状态，不触发 live 采集、不推送，适合 hermes/launchd 排障。
"""
from __future__ import annotations

import json
from datetime import timezone

from common import clock


def _latest_row(store, table: str):
    return store.conn.execute(
        f"SELECT * FROM {table} ORDER BY ts DESC LIMIT 1"
    ).fetchone()


def _count(store, sql: str, params: tuple = ()) -> int:
    return int(store.conn.execute(sql, params).fetchone()[0])


def _age(now: int, ts: int | None) -> int | None:
    return None if ts is None else max(0, now - int(ts))


def _fmt_ts(ts: int | None) -> str:
    if ts is None:
        return "-"
    return clock.from_ts(int(ts)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def check_health(store, cfg, *, now: int | None = None) -> dict:
    """返回结构化健康报告。status=ok/warn，warn 表示可运行但需关注。"""
    n = clock.now_ts() if now is None else now
    symbol = cfg.require("meta.symbol")
    primary = cfg.require("timeframes.primary")
    tf_sec = clock.tf_seconds(primary)
    max_stale = int(cfg.get("ops.health.max_kline_stale_sec", tf_sec * 2))

    wal_mode = store.conn.execute("PRAGMA journal_mode;").fetchone()[0].lower()
    kline_rows = store.klines(primary, limit=1)
    latest_kline_ts = int(kline_rows[-1]["ts"]) if kline_rows else None
    expected_closed = clock.last_closed_ts(primary, now=n)
    kline_lag = None if latest_kline_ts is None else max(0, expected_closed - latest_kline_ts)

    latest_snapshot = _latest_row(store, "snapshots")
    latest_analysis = _latest_row(store, "analyses")
    latest_push = _latest_row(store, "push_events")

    ttl = int(cfg.get("plan_builder.signal_ttl_klines", 4))
    settle_cutoff = n - (ttl + 1) * tf_sec
    unsettled_total = _count(store, "SELECT COUNT(*) FROM analyses WHERE outcome IS NULL")
    unsettled_due = len(store.unsettled_analyses(before_ts=settle_cutoff))

    checks = {
        "database": {
            "ok": wal_mode == "wal",
            "path": str(store.db_path),
            "wal_mode": wal_mode,
        },
        "klines": {
            "ok": latest_kline_ts is not None and (kline_lag or 0) <= max_stale,
            "timeframe": primary,
            "latest_ts": latest_kline_ts,
            "latest_utc": _fmt_ts(latest_kline_ts),
            "expected_closed_ts": expected_closed,
            "lag_sec": kline_lag,
            "max_stale_sec": max_stale,
        },
        "snapshot": {
            "ok": latest_snapshot is not None,
            "snapshot_id": latest_snapshot["snapshot_id"] if latest_snapshot else None,
            "latest_ts": int(latest_snapshot["ts"]) if latest_snapshot else None,
            "latest_utc": _fmt_ts(latest_snapshot["ts"] if latest_snapshot else None),
            "age_sec": _age(n, latest_snapshot["ts"] if latest_snapshot else None),
        },
        "analysis": {
            "ok": latest_analysis is not None,
            "id": int(latest_analysis["id"]) if latest_analysis else None,
            "latest_ts": int(latest_analysis["ts"]) if latest_analysis else None,
            "latest_utc": _fmt_ts(latest_analysis["ts"] if latest_analysis else None),
            "age_sec": _age(n, latest_analysis["ts"] if latest_analysis else None),
            "outcome": latest_analysis["outcome"] if latest_analysis else None,
        },
        "settlement": {
            "ok": unsettled_due == 0,
            "unsettled_total": unsettled_total,
            "unsettled_due": unsettled_due,
            "settle_cutoff_ts": settle_cutoff,
        },
        "push": {
            "ok": True,
            "id": int(latest_push["id"]) if latest_push else None,
            "latest_ts": int(latest_push["ts"]) if latest_push else None,
            "latest_utc": _fmt_ts(latest_push["ts"] if latest_push else None),
            "age_sec": _age(n, latest_push["ts"] if latest_push else None),
            "signature": latest_push["signature"] if latest_push else None,
            "analysis_id": latest_push["analysis_id"] if latest_push else None,
        },
    }
    status = "ok" if all(v["ok"] for v in checks.values()) else "warn"
    return {
        "status": status,
        "symbol": symbol,
        "now_ts": n,
        "now_utc": _fmt_ts(n),
        "checks": checks,
    }


def render_health(report: dict) -> str:
    c = report["checks"]
    lines = [
        f"健康检查 {report['symbol']} status={report['status']}",
        f"db: wal={c['database']['wal_mode']} path={c['database']['path']}",
        (
            f"klines: tf={c['klines']['timeframe']} latest={c['klines']['latest_utc']} "
            f"lag={c['klines']['lag_sec']}s max={c['klines']['max_stale_sec']}s"
        ),
        (
            f"snapshot: latest={c['snapshot']['latest_utc']} "
            f"id={c['snapshot']['snapshot_id'] or '-'}"
        ),
        (
            f"analysis: latest={c['analysis']['latest_utc']} "
            f"id={c['analysis']['id'] or '-'} outcome={c['analysis']['outcome'] or '-'}"
        ),
        (
            f"settlement: unsettled={c['settlement']['unsettled_total']} "
            f"due={c['settlement']['unsettled_due']}"
        ),
        (
            f"push: latest={c['push']['latest_utc']} "
            f"id={c['push']['id'] or '-'} analysis_id={c['push']['analysis_id'] or '-'}"
        ),
    ]
    return "\n".join(lines)


def health_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
