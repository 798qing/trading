"""预采集：一次性 live 采集 → 落库 → 分析 → persist，然后退出。

由 launchd 每 15 分钟调一次（StartInterval=900），养"热"数据库，
使 /btc 走热路径秒回（缺口10 request_policy）。**只采数据不推送**（架构七节）。
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from analyze import analyze, persist
from backtest.settle import settle_due
from common.config import load_config
from common.config_watcher import ConfigWatcher
from data.collectors.okx import OKXError, OKXClient
from data.store import Store

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s precompute | %(message)s")
log = logging.getLogger("precompute")


def cycle(cfg=None) -> int:
    cfg = cfg or load_config()
    store = Store(cfg.db_path)
    store.init_db()
    try:
        with OKXClient(timeout=cfg.get("ops.llm.timeout_sec", 20)) as okx:
            a = analyze(store, cfg, okx=okx)
        aid = persist(store, cfg, a)
        settled = settle_due(store, cfg)        # P0-2：每根收线扫描回填到期信号
        log.info("snapshot=%s score=%s dir=%s rec=%s analysis_id=%s dq_complete=%s settled=%s",
                 a.snapshot.snapshot_id, a.fusion.score, a.fusion.direction,
                 a.recommendation, aid, a.snapshot.data_quality.get("is_complete"), settled)
        return 0
    except OKXError as e:
        log.error("采集失败（OKX）：%s", e)
        return 2
    except Exception:
        log.exception("预采集异常")
        return 1
    finally:
        store.close()


def watch_loop(*, max_cycles: int | None = None) -> int:
    """长运行预采集：按周期跑 cycle，并在周期之间热重载配置。"""
    watcher = ConfigWatcher()
    cfg = watcher.load_initial()
    log.info("config_loaded version=%s path=%s", cfg.version, cfg.path)

    cycles = 0
    next_cycle = 0.0
    while True:
        result = watcher.poll()
        if result.changed and result.error:
            log.warning("config_reload_failed keep=%s error=%s",
                        result.current_version, result.error)
        elif result.changed:
            cfg = result.config
            log.info("config_reloaded %s -> %s", result.previous_version,
                     result.current_version)

        now = time.monotonic()
        if now >= next_cycle:
            rc = cycle(cfg)
            cycles += 1
            interval = int(cfg.get("ops.precompute_interval_min", 15)) * 60
            next_cycle = now + max(60, interval)
            if max_cycles is not None and cycles >= max_cycles:
                return rc

        watch_interval = int(cfg.get("ops.config_watcher_interval_sec", 30))
        sleep_for = min(max(1, watch_interval), max(1, next_cycle - time.monotonic()))
        time.sleep(sleep_for)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="precompute")
    p.add_argument("--watch", action="store_true",
                   help="长运行模式：周期预采集，并热重载配置")
    p.add_argument("--max-cycles", type=int,
                   help="watch 模式最多执行 N 个采集周期（测试/排障用）")
    args = p.parse_args(argv)
    if args.watch:
        return watch_loop(max_cycles=args.max_cycles)
    return cycle()


if __name__ == "__main__":
    sys.exit(main())
