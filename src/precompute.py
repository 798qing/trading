"""预采集：一次性 live 采集 → 落库 → 分析 → persist，然后退出。

由 launchd 每 15 分钟调一次（StartInterval=900），养"热"数据库，
使 /btc 走热路径秒回（缺口10 request_policy）。**只采数据不推送**（架构七节）。
"""
from __future__ import annotations

import logging
import sys

from analyze import analyze, persist
from common.config import load_config
from data.collectors.okx import OKXError, OKXClient
from data.store import Store

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s precompute | %(message)s")
log = logging.getLogger("precompute")


def cycle() -> int:
    cfg = load_config()
    store = Store(cfg.db_path)
    store.init_db()
    try:
        with OKXClient(timeout=cfg.get("ops.llm.timeout_sec", 20)) as okx:
            a = analyze(store, cfg, okx=okx)
        aid = persist(store, cfg, a)
        log.info("snapshot=%s score=%s dir=%s rec=%s analysis_id=%s dq_complete=%s",
                 a.snapshot.snapshot_id, a.fusion.score, a.fusion.direction,
                 a.recommendation, aid, a.snapshot.data_quality.get("is_complete"))
        return 0
    except OKXError as e:
        log.error("采集失败（OKX）：%s", e)
        return 2
    except Exception:
        log.exception("预采集异常")
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(cycle())
