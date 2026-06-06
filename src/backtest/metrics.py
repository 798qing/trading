"""阶段3 回测统计：胜率、EV、MDD、Sortino。

输入来自 analyses 的已结算生命周期字段；未成交 expired/no_trade 不进入胜负
分母，EV/MDD/Sortino 只使用 outcome_note 里的 pnl_net 样本。
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Iterable

_PNL_RE = re.compile(r"pnl_net=([-+]?\d+(?:\.\d+)?)%")


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


def metrics_report(store, cfg, *, days: int | None = 30, now: int | None = None
                   ) -> dict:
    """读取已结算 analyses，返回 overall + 按版本分组的报告。"""
    since = None
    if days is not None:
        from common import clock

        n = clock.now_ts() if now is None else now
        since = n - days * 86400
    rows = store.settled_analyses(since_ts=since, symbol=cfg.require("meta.symbol"))
    overall = compute_metrics(rows)
    return {
        "symbol": cfg.require("meta.symbol"),
        "days": days,
        "overall": overall.to_dict(),
        "groups": [m.to_dict() for m in grouped_metrics(rows)],
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
    return "\n".join(lines)


def report_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
