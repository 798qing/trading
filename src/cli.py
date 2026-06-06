"""命令行入口：跑一次分析并打印卡片/JSON。供 hermes skill 调用；显式 --push 才碰 Telegram。

热路径（默认）：用 precompute 落库的最新数据**本地重算**，亚秒返回，不 live 拉 OKX。
冷/强制刷新（--refresh，或库里没数据）：live 采集 OKX（2–4s）。

用法：
    python -m cli                 # 默认卡（观望/信号），读热库
    python -m cli --quick         # 快报
    python -m cli --json          # 结构化 JSON（供 hermes 二次加工/LLM 解读）
    python -m cli --llm           # full-analysis LLM 解读，失败自动降级
    python -m cli --refresh       # 强制 live 采集最新
    python -m cli --history       # 最近分析/结算流水
    python -m cli --stats         # 已结算信号回测统计
    python -m cli --auto-weight   # 自动权重建议（只读，不改配置）
    python -m cli --sample-progress # 采样进度/防空转巡检
    python -m cli --probe-sources # 外部源权限/可用性探针
    python -m cli --health        # 运行健康检查
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
from llm.strategist import full_analysis
from output import card_builder as cb
from output.rollback import maybe_revoke_on_wick
from output.push_service import push_once
from output.telegram import TelegramClient, TelegramError


def _persist(store, cfg, a, *, required: bool) -> int | None:
    try:
        return persist(store, cfg, a)
    except Exception as e:  # noqa: BLE001
        if required:
            raise RuntimeError(f"落库失败，取消推送：{e}") from e
        return None


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
        "llm_output": a.llm_output,
        "data_quality": a.snapshot.data_quality,
        "signals": {k: {"direction": v["direction"], "strength": v["strength"],
                        "events": v["events"]} for k, v in a.signals.items()},
    }


def _run_stats(args, cfg, store) -> int:
    from backtest.metrics import metrics_report, render_report, report_json

    days = None if args.all_history else args.days
    report = metrics_report(store, cfg, days=days)
    if args.json:
        print(report_json(report))
    else:
        print(render_report(report))
    return 0


def _run_history(args, cfg, store) -> int:
    from ops.history import history_json, history_report, render_history

    days = None if args.all_history else args.days
    report = history_report(
        store, cfg, days=days, limit=args.limit, outcome=args.outcome,
    )
    if args.json:
        print(history_json(report))
    else:
        print(render_history(report, timezone=cfg.get("display.timezone", "Asia/Shanghai")))
    return 0


def _run_health(args, cfg, store) -> int:
    from ops.health import check_health, health_json, render_health

    report = check_health(store, cfg)
    if args.json:
        print(health_json(report))
    else:
        print(render_health(report))
    return 0 if report["status"] == "ok" else 1


def _run_auto_weight(args, cfg, store) -> int:
    from backtest.weighting import render_weight_report, weight_report

    days = None if args.all_history else args.days
    report = weight_report(store, cfg, days=days)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_weight_report(report))
    return 0


def _run_sample_progress(args, cfg, store) -> int:
    from ops.sample_progress import (
        render_sample_progress,
        sample_progress_json,
        sample_progress_report,
    )

    days = None if args.all_history else args.days
    report = sample_progress_report(store, cfg, days=days)
    if args.json:
        print(sample_progress_json(report))
    else:
        print(render_sample_progress(
            report, timezone=cfg.get("display.timezone", "Asia/Shanghai"),
        ))
    return 0


def _run_probe_sources(args, cfg) -> int:
    report: dict[str, dict] = {}

    cg_key = cfg.secret("COINGLASS_API_KEY")
    report["coinglass_etf"] = {"key_present": bool(cg_key)}
    if cg_key:
        try:
            from data.collectors.coinglass import CoinGlassClient

            with CoinGlassClient(api_key=cg_key, timeout=20.0) as cg:
                rows = cg.bitcoin_etf_flows(ticker="IBIT", limit=3)
            latest = rows[-1] if rows else None
            report["coinglass_etf"].update({
                "ok": bool(rows),
                "rows": len(rows),
                "latest": ({
                    "ts": latest.ts,
                    "ticker": latest.ticker,
                    "net_flow_usd": latest.net_flow_usd,
                    "total_value_usd": latest.total_value_usd,
                } if latest else None),
            })
        except Exception as e:  # noqa: BLE001
            report["coinglass_etf"].update({"ok": False, "error": f"{type(e).__name__}: {e}"})
    else:
        report["coinglass_etf"].update({"ok": False, "error": "missing COINGLASS_API_KEY"})

    try:
        from data.collectors.macro import YahooMacroClient, snapshot_to_source

        with YahooMacroClient(timeout=20.0) as macro:
            src = snapshot_to_source(macro.rolling_linkage())
        report["macro"] = {"ok": True, "source": src}
    except Exception as e:  # noqa: BLE001
        report["macro"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(item.get("ok") for item in report.values()) else 1


def run(args) -> int:
    cfg = load_config()
    store = Store(cfg.db_path)
    store.init_db()
    if args.health:
        try:
            return _run_health(args, cfg, store)
        finally:
            store.close()

    if args.history:
        try:
            return _run_history(args, cfg, store)
        finally:
            store.close()

    if args.stats:
        try:
            return _run_stats(args, cfg, store)
        finally:
            store.close()

    if args.auto_weight:
        try:
            return _run_auto_weight(args, cfg, store)
        finally:
            store.close()

    if args.sample_progress:
        try:
            return _run_sample_progress(args, cfg, store)
        finally:
            store.close()

    if args.probe_sources:
        try:
            return _run_probe_sources(args, cfg)
        finally:
            store.close()

    primary = cfg.require("timeframes.primary")

    live = args.refresh or not has_klines(store, primary)
    analysis_id = None
    card = None
    try:
        if live:
            with OKXClient(timeout=cfg.get("ops.llm.timeout_sec", 20)) as okx:
                a = analyze(store, cfg, okx=okx)
            if args.llm and not args.quick:
                a.llm_output = full_analysis(a, cfg).to_dict()
            analysis_id = _persist(store, cfg, a, required=args.push)
        else:
            # 热路径：用库里最新数据 + 最近快照的外部源重建，本地重算
            snap = build_snapshot(store, cfg, latest_sources(store), persist=False)
            a = analyze(store, cfg, snapshot=snap)
            if args.llm and not args.quick:
                a.llm_output = full_analysis(a, cfg).to_dict()
            if args.push:
                analysis_id = _persist(store, cfg, a, required=True)
        if not args.json:
            card = cb.render(a, cfg, quick=args.quick)
        if args.push:
            own_tg = None
            if cfg.secret("TELEGRAM_BOT_TOKEN"):
                own_tg = TelegramClient(cfg.secret("TELEGRAM_BOT_TOKEN"))
                rollback = maybe_revoke_on_wick(a, cfg, store, telegram=own_tg)
                if rollback.revoked:
                    print(f"push_revoked={rollback.reason} event_id={rollback.push_event_id}",
                          file=sys.stderr)
            push_text = cb.render(a, cfg, quick=False)
            try:
                result = push_once(a, cfg, store, telegram=own_tg,
                                   analysis_id=analysis_id, text=push_text)
                if result.sent:
                    print(f"push={result.decision.reason} event_id={result.push_event_id}",
                          file=sys.stderr)
                else:
                    print(f"push_skipped={result.decision.reason}", file=sys.stderr)
            finally:
                if own_tg is not None:
                    own_tg.close()
    except OKXError as e:
        print(f"⚠️ 数据源不可用：{e}", file=sys.stderr)
        return 2
    except TelegramError as e:
        print(f"⚠️ Telegram 推送失败：{e}", file=sys.stderr)
        return 3
    except RuntimeError as e:
        print(f"⚠️ {e}", file=sys.stderr)
        return 1
    finally:
        store.close()

    if args.json:
        print(json.dumps(_summary_json(a, cfg), ensure_ascii=False, indent=2))
    else:
        print(card)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="trading-agent", description="BTC 分析卡片")
    p.add_argument("--quick", action="store_true", help="快报模式")
    p.add_argument("--json", action="store_true", help="输出结构化 JSON")
    p.add_argument("--llm", action="store_true",
                   help="启用 full-analysis LLM 综合解读；失败自动降级为纯检测器")
    p.add_argument("--refresh", action="store_true", help="强制 live 采集最新")
    p.add_argument("--push", action="store_true", help="按阶段2推送规则发送 Telegram")
    p.add_argument("--history", action="store_true", help="输出最近分析/结算流水")
    p.add_argument("--stats", action="store_true", help="输出已结算信号回测统计")
    p.add_argument("--auto-weight", action="store_true",
                   help="输出自动调权重建议（只读，不改配置）")
    p.add_argument("--sample-progress", action="store_true",
                   help="输出阶段3采样进度/防空转巡检")
    p.add_argument("--probe-sources", action="store_true",
                   help="探测 CoinGlass ETF / 宏观源可用性，不打印密钥")
    p.add_argument("--health", action="store_true", help="检查数据库/热库/结算/推送状态")
    p.add_argument("--days", type=int, default=30, help="统计最近 N 天，默认 30")
    p.add_argument("--all-history", action="store_true", help="统计全部历史")
    p.add_argument("--limit", type=int, default=10, help="history 最多返回 N 条，默认 10")
    p.add_argument("--outcome", choices=[
        "pending", "correct", "wrong", "partial", "expired", "no_trade",
    ], help="history 按结算结果过滤")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
