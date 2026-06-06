"""阶段3 回测统计：胜率、EV、MDD、Sortino。

输入来自 analyses 的已结算生命周期字段；未成交 expired/no_trade 不进入胜负
分母，EV/MDD/Sortino 只使用 outcome_note 里的 pnl_net 样本。
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

_PNL_RE = re.compile(r"pnl_net=([-+]?\d+(?:\.\d+)?)%")
_REGIME_LABELS = {
    "trend": "趋势",
    "range": "震荡",
    "transition": "过渡",
    "unknown": "未知",
}
_REGIME_ALIASES = {
    "trend": "trend",
    "trending": "trend",
    "strong_trend": "trend",
    "趋势": "trend",
    "range": "range",
    "ranging": "range",
    "sideways": "range",
    "oscillation": "range",
    "震荡": "range",
    "transition": "transition",
    "transitioning": "transition",
    "transitional": "transition",
    "过渡": "transition",
}


@dataclass(frozen=True)
class Metrics:
    prompt_version: str
    config_version: str
    total: int
    entered: int
    wins: int
    losses: int
    partials: int
    expired: int
    no_trade: int
    pnl_samples: int
    win_rate: float | None
    ev_pct: float | None
    total_return_pct: float | None
    max_drawdown_pct: float | None
    sortino: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def _version(row, key: str) -> str:
    return row[key] or "unknown"


def pnl_from_note(note: str | None) -> float | None:
    """从 settle 写入的 outcome_note 提取净收益百分比。"""
    if not note:
        return None
    m = _PNL_RE.search(note)
    return float(m.group(1)) if m else None


def _max_drawdown(pnls_pct: list[float]) -> float | None:
    if not pnls_pct:
        return None
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for pct in pnls_pct:
        equity *= max(0.0, 1.0 + pct / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd * 100.0


def _sortino(pnls_pct: list[float]) -> float | None:
    if not pnls_pct:
        return None
    rets = [p / 100.0 for p in pnls_pct]
    downside = [min(0.0, r) for r in rets]
    downside_dev = math.sqrt(sum(d * d for d in downside) / len(rets))
    if downside_dev == 0:
        return None
    return (sum(rets) / len(rets)) / downside_dev


def _total_return(pnls_pct: list[float]) -> float | None:
    if not pnls_pct:
        return None
    equity = 1.0
    for pct in pnls_pct:
        equity *= max(0.0, 1.0 + pct / 100.0)
    return (equity - 1.0) * 100.0


def compute_metrics(rows: Iterable) -> Metrics:
    rows = list(rows)
    prompt_versions = {_version(r, "prompt_version") for r in rows}
    config_versions = {_version(r, "config_version") for r in rows}
    prompt_version = next(iter(prompt_versions)) if len(prompt_versions) == 1 else (
        "none" if not prompt_versions else "mixed"
    )
    config_version = next(iter(config_versions)) if len(config_versions) == 1 else (
        "none" if not config_versions else "mixed"
    )

    outcomes = [r["outcome"] for r in rows]
    wins = outcomes.count("correct")
    losses = outcomes.count("wrong")
    partials = outcomes.count("partial")
    expired = outcomes.count("expired")
    no_trade = outcomes.count("no_trade")
    entered = wins + losses + partials
    pnls = [p for p in (pnl_from_note(r["outcome_note"]) for r in rows) if p is not None]
    win_rate = wins / entered if entered else None
    ev = sum(pnls) / len(pnls) if pnls else None

    return Metrics(
        prompt_version=prompt_version,
        config_version=config_version,
        total=len(rows),
        entered=entered,
        wins=wins,
        losses=losses,
        partials=partials,
        expired=expired,
        no_trade=no_trade,
        pnl_samples=len(pnls),
        win_rate=win_rate,
        ev_pct=ev,
        total_return_pct=_total_return(pnls),
        max_drawdown_pct=_max_drawdown(pnls),
        sortino=_sortino(pnls),
    )


def grouped_metrics(rows: Iterable) -> list[Metrics]:
    groups: dict[tuple[str, str], list] = {}
    for r in rows:
        key = (_version(r, "prompt_version"), _version(r, "config_version"))
        groups.setdefault(key, []).append(r)
    return [
        compute_metrics(groups[k])
        for k in sorted(groups, key=lambda x: (x[0], x[1]))
    ]


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


def _normalize_regime(value: str | None) -> str | None:
    if not value:
        return None
    return _REGIME_ALIASES.get(str(value).strip().lower())


def _strength_at_least(value: Any, threshold: int) -> bool:
    if value is None:
        return True
    try:
        return int(value) >= threshold
    except (TypeError, ValueError):
        return False


def infer_market_regime(signals: Iterable[dict[str, Any]],
                        market_state: str | None = None) -> str:
    """从冻结快照的 market_state/signals 推断回测行情桶。"""
    normalized = _normalize_regime(market_state)
    if normalized:
        return normalized

    by_module = {str(s.get("module")): s for s in signals if s.get("module")}
    adx_details = _safe_json(by_module.get("adx", {}).get("details"))
    structure_details = _safe_json(by_module.get("structure", {}).get("details"))
    vol_details = _safe_json(by_module.get("vol_regime", {}).get("details"))

    adx_class = str(adx_details.get("classification") or "").lower()
    structure = str(structure_details.get("structure") or "").lower()
    vol_regime = str(vol_details.get("regime") or "").lower()
    directions = {
        s.get("direction")
        for s in signals
        if s.get("direction") in {"bullish", "bearish"}
        and _strength_at_least(s.get("strength"), 3)
    }

    if vol_regime == "high_vol" and (
        len(directions) > 1 or adx_class == "no_trend" or structure == "range"
    ):
        return "transition"
    if adx_class in {"strong", "trending"} or structure in {"uptrend", "downtrend"}:
        return "trend"
    if adx_class == "no_trend" or structure == "range":
        return "range"
    if vol_regime == "high_vol":
        return "transition"
    return "unknown"


def _fetch_regime_context(store, snapshot_ids: Iterable[str]) -> dict[str, dict]:
    ids = sorted({sid for sid in snapshot_ids if sid})
    ctx = {sid: {"market_state": None, "signals": []} for sid in ids}
    if not ids:
        return ctx

    chunk_size = 900
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i:i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        for row in store.conn.execute(
            f"SELECT snapshot_id, market_state FROM snapshots "
            f"WHERE snapshot_id IN ({placeholders})",
            chunk,
        ).fetchall():
            ctx[row["snapshot_id"]]["market_state"] = row["market_state"]
        for row in store.conn.execute(
            f"SELECT snapshot_id, module, direction, strength, confidence, details "
            f"FROM signals WHERE snapshot_id IN ({placeholders})",
            chunk,
        ).fetchall():
            ctx[row["snapshot_id"]]["signals"].append({
                "module": row["module"],
                "direction": row["direction"],
                "strength": row["strength"],
                "confidence": row["confidence"],
                "details": _safe_json(row["details"]),
            })
    return ctx


def _attach_market_regimes(store, rows: Iterable) -> list[dict[str, Any]]:
    enriched = [dict(r) for r in rows]
    ctx = _fetch_regime_context(store, (r.get("snapshot_id") for r in enriched))
    for row in enriched:
        snap_ctx = ctx.get(row.get("snapshot_id"), {})
        row["_market_regime"] = infer_market_regime(
            snap_ctx.get("signals", []),
            snap_ctx.get("market_state"),
        )
    return enriched


def regime_metrics(rows: Iterable) -> list[dict[str, Any]]:
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r.get("_market_regime") or "unknown", []).append(r)

    order = {"trend": 0, "range": 1, "transition": 2, "unknown": 3}
    result: list[dict[str, Any]] = []
    for regime in sorted(groups, key=lambda x: (order.get(x, 99), x)):
        d = compute_metrics(groups[regime]).to_dict()
        d["market_regime"] = regime
        d["market_regime_label"] = _REGIME_LABELS.get(regime, regime)
        result.append(d)
    return result


def metrics_report(store, cfg, *, days: int | None = 30, now: int | None = None
                   ) -> dict:
    """读取已结算 analyses，返回 overall + 版本/行情类型分组报告。"""
    since = None
    if days is not None:
        from common import clock

        n = clock.now_ts() if now is None else now
        since = n - days * 86400
    raw_rows = store.settled_analyses(since_ts=since, symbol=cfg.require("meta.symbol"))
    rows = _attach_market_regimes(store, raw_rows)
    overall = compute_metrics(rows)
    return {
        "symbol": cfg.require("meta.symbol"),
        "days": days,
        "overall": overall.to_dict(),
        "groups": [m.to_dict() for m in grouped_metrics(rows)],
        "regimes": regime_metrics(rows),
    }


def _pct(v: float | None, digits: int = 1) -> str:
    return "-" if v is None else f"{v:.{digits}f}%"


def _num(v: float | None, digits: int = 2) -> str:
    return "-" if v is None else f"{v:.{digits}f}"


def render_report(report: dict) -> str:
    """终端/Telegram 友好的短文本报告。"""
    overall = report["overall"]
    title_days = "all" if report["days"] is None else f"{report['days']}d"
    lines = [
        f"回测统计 {report['symbol']} ({title_days})",
        (
            f"overall: total={overall['total']} entered={overall['entered']} "
            f"win={_pct(None if overall['win_rate'] is None else overall['win_rate'] * 100)} "
            f"EV={_pct(overall['ev_pct'])} MDD={_pct(overall['max_drawdown_pct'])} "
            f"Sortino={_num(overall['sortino'])}"
        ),
    ]
    if report["groups"]:
        lines.append("by version:")
    for g in report["groups"]:
        lines.append(
            f"- prompt={g['prompt_version']} cfg={g['config_version']} "
            f"n={g['entered']}/{g['total']} win="
            f"{_pct(None if g['win_rate'] is None else g['win_rate'] * 100)} "
            f"EV={_pct(g['ev_pct'])} MDD={_pct(g['max_drawdown_pct'])} "
            f"Sortino={_num(g['sortino'])}"
        )
    if report.get("regimes"):
        lines.append("by regime:")
    for g in report.get("regimes", []):
        label = g.get("market_regime_label") or g.get("market_regime")
        lines.append(
            f"- {label}({g['market_regime']}): n={g['entered']}/{g['total']} "
            f"win={_pct(None if g['win_rate'] is None else g['win_rate'] * 100)} "
            f"EV={_pct(g['ev_pct'])} MDD={_pct(g['max_drawdown_pct'])} "
            f"Sortino={_num(g['sortino'])}"
        )
    return "\n".join(lines)


def report_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
