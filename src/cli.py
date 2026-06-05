"""命令行入口：跑一次分析并打印卡片/JSON。供 hermes skill 调用，不碰 Telegram。

热路径（默认）：用 precompute 落库的最新数据**本地重算**，亚秒返回，不 live 拉 OKX。
冷/强制刷新（--refresh，或库里没数据）：live 采集 OKX（2–4s）。

用法：
    python -m cli                 # 默认卡（观望/信号），读热库
    python -m cli --quick         # 快报
    python -m cli --json          # 结构化 JSON（供 hermes 二次加工/LLM 解读）
    python -m cli --refresh       # 强制 live 采集最新
"""
from __future__ import annotations

import argparse
import json
import sys

from analyze import analyze, persist
from common.config import load_config
from data.collectors.okx import OKXClient, OKXError
from data.snapshot import build_snapshot, has_klines, latest_sources
from data.store import Store
from output import card_builder as cb


def _summary_json(a, cfg) -> dict:
    """给 hermes/LLM 的结构化包（不含裸 K 线，含信号/评分/计划）。"""
    return {
        "symbol": a.snapshot.symbol,
        "snapshot_id": a.snapshot.snapshot_id,
        "analysis_ts": a.snapshot.analysis_ts,
        "config_version": cfg.version,
        "score": a.fusion.score,
        "direction": a.fusion.direction,
        "recommendation": a.recommendation,
        "reasons": a.reasons,
        "vetoed": a.fusion.vetoed,
        "veto_reasons": a.fusion.veto_reasons,
        "hard_constraints": a.fusion.hard_constraints,
        "radar": a.fusion.radar,
        "subscores": a.fusion.subscores,
        "conflicts": a.fusion.conflicts,
        "timeframe_alignment": a.fusion.timeframe_alignment,
        "plan": a.plan.to_dict(),
        "risk": {"warnings": a.risk.warnings,
                 "position_advice": a.risk.position_advice},
        "data_quality": a.snapshot.data_quality,
        "signals": {k: {"direction": v["direction"], "strength": v["strength"],
                        "events": v["events"]} for k, v in a.signals.items()},
    }


def run(args) -> int:
    cfg = load_config()
    store = Store(cfg.get("ops.db_path", "data/trading.db"))
    store.init_db()
    primary = cfg.require("timeframes.primary")

    live = args.refresh or not has_klines(store, primary)
    try:
        if live:
            with OKXClient(timeout=cfg.get("ops.llm.timeout_sec", 20)) as okx:
                a = analyze(store, cfg, okx=okx)
            try:
                persist(store, cfg, a)
            except Exception:
                pass
        else:
            # 热路径：用库里最新数据 + 最近快照的外部源重建，本地重算
            snap = build_snapshot(store, cfg, latest_sources(store), persist=False)
            a = analyze(store, cfg, snapshot=snap)
    except OKXError as e:
        print(f"⚠️ 数据源不可用：{e}", file=sys.stderr)
        return 2
    finally:
        store.close()

    if args.json:
        print(json.dumps(_summary_json(a, cfg), ensure_ascii=False, indent=2))
    else:
        print(cb.render(a, cfg, quick=args.quick))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="trading-agent", description="BTC 分析卡片")
    p.add_argument("--quick", action="store_true", help="快报模式")
    p.add_argument("--json", action="store_true", help="输出结构化 JSON")
    p.add_argument("--refresh", action="store_true", help="强制 live 采集最新")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
