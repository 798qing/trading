"""SQLite 持久化（D9：WAL 模式 + 单写入者）。

WAL 让“预采集写 + 分析/回测读”并发而不报 database is locked。
约定：全进程只用一个 Store 实例做写入（单写入者）；只读方用 connect_readonly()。
所有时间戳为 UTC epoch 秒（D8）。snapshots / analyses 带 config_version（P0-4）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

# K 线表统一结构；按周期分表（架构八节）
_KLINE_TFS = ("5m", "15m", "1h", "4h", "1d")

_PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA synchronous=NORMAL;",     # WAL 下 NORMAL 已安全且更快
    "PRAGMA foreign_keys=ON;",
    "PRAGMA busy_timeout=5000;",      # 写锁竞争时最多等 5s 再报错
)


def _kline_ddl(tf: str) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS kline_{tf} (
        ts      INTEGER PRIMARY KEY,   -- K 线开盘时间，UTC epoch 秒
        open    REAL NOT NULL,
        high    REAL NOT NULL,
        low     REAL NOT NULL,
        close   REAL NOT NULL,
        volume  REAL NOT NULL
    );
    """


_SCHEMA = [
    *[_kline_ddl(tf) for tf in _KLINE_TFS],
    # 冻结快照：所有下游统一引用 snapshot_id（D6）
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        snapshot_id     TEXT PRIMARY KEY,
        ts              INTEGER NOT NULL,
        symbol          TEXT NOT NULL,
        market_state    TEXT,                  -- trending/ranging/transitioning
        payload         TEXT NOT NULL,         -- JSON：各源数据 + as_of_ts
        data_quality    TEXT NOT NULL,         -- JSON：is_complete/warnings
        config_version  TEXT NOT NULL          -- P0-4
    );
    """,
    # 分析结果：含完整生命周期字段（P0-1）+ 版本字段（P0-4/prompt_version）
    """
    CREATE TABLE IF NOT EXISTS analyses (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts              INTEGER NOT NULL,
        snapshot_id     TEXT NOT NULL,
        symbol          TEXT NOT NULL,
        score           INTEGER,
        direction       TEXT,                  -- bullish/bearish/neutral
        plan            TEXT,                  -- JSON：plan_builder 输出（价格唯一来源）
        llm_output      TEXT,
        card_text       TEXT,
        prompt_version  TEXT,                  -- LLM Skill 版本（回测分组）
        config_version  TEXT,                  -- 当时的配置指纹
        outcome         TEXT,                  -- correct/wrong/partial/expired
        outcome_note    TEXT,
        entry_hit       INTEGER,               -- 是否成交 0/1
        exit_reason     TEXT,                  -- sl_hit/tp_hit/expired/manual
        settled_ts      INTEGER,               -- 结算回填时间（P0-2）
        FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id)
    );
    """,
    # 各检器原始输出（统一 schema）
    """
    CREATE TABLE IF NOT EXISTS signals (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          INTEGER NOT NULL,
        snapshot_id TEXT NOT NULL,
        module      TEXT NOT NULL,
        direction   TEXT,
        strength    INTEGER,
        confidence  TEXT,
        details     TEXT,                      -- JSON
        FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id)
    );
    """,
    # 背景层（日级）
    """
    CREATE TABLE IF NOT EXISTS onchain (
        ts                INTEGER PRIMARY KEY,
        exchange_netflow  REAL,
        fear_greed        INTEGER,
        extra             TEXT                 -- JSON
    );
    """,
    # 宏观/风险事件
    """
    CREATE TABLE IF NOT EXISTS events (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ts        INTEGER NOT NULL,
        source    TEXT,
        severity  TEXT,
        category  TEXT,
        summary   TEXT
    );
    """,
    # 常用查询索引
    "CREATE INDEX IF NOT EXISTS idx_analyses_ts ON analyses(ts);",
    "CREATE INDEX IF NOT EXISTS idx_analyses_outcome ON analyses(outcome);",
    "CREATE INDEX IF NOT EXISTS idx_signals_snapshot ON signals(snapshot_id);",
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);",
]


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    for p in _PRAGMAS:
        conn.execute(p)


class Store:
    """单写入者写连接 + 按需只读连接。

    用法：
        store = Store("data/trading.db")
        store.init_db()
        store.upsert_klines("15m", rows)
        ...
        store.close()
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, isolation_level=None)  # autocommit
        self.conn.row_factory = sqlite3.Row
        _apply_pragmas(self.conn)

    # --- schema ---
    def init_db(self) -> None:
        cur = self.conn.cursor()
        for stmt in _SCHEMA:
            cur.execute(stmt)

    # --- K 线 ---
    def upsert_klines(self, tf: str, rows: list[tuple]) -> int:
        """rows: [(ts, open, high, low, close, volume), ...]。按 ts 幂等覆盖。"""
        if tf not in _KLINE_TFS:
            raise ValueError(f"未知周期 {tf}，允许 {_KLINE_TFS}")
        sql = (f"INSERT INTO kline_{tf} (ts,open,high,low,close,volume) "
               f"VALUES (?,?,?,?,?,?) "
               f"ON CONFLICT(ts) DO UPDATE SET "
               f"open=excluded.open,high=excluded.high,low=excluded.low,"
               f"close=excluded.close,volume=excluded.volume")
        self.conn.executemany(sql, rows)
        return len(rows)

    def klines(self, tf: str, limit: int = 300, before_ts: int | None = None
               ) -> list[sqlite3.Row]:
        """取最近 limit 根，按 ts 升序返回。before_ts 用于回测重放（只取该时刻前）。"""
        if tf not in _KLINE_TFS:
            raise ValueError(f"未知周期 {tf}")
        if before_ts is None:
            q = (f"SELECT * FROM (SELECT * FROM kline_{tf} ORDER BY ts DESC "
                 f"LIMIT ?) ORDER BY ts ASC")
            return self.conn.execute(q, (limit,)).fetchall()
        q = (f"SELECT * FROM (SELECT * FROM kline_{tf} WHERE ts<=? ORDER BY ts DESC "
             f"LIMIT ?) ORDER BY ts ASC")
        return self.conn.execute(q, (before_ts, limit)).fetchall()

    def klines_after(self, tf: str, after_ts: int, limit: int = 8
                     ) -> list[sqlite3.Row]:
        """取 ts 严格大于 after_ts 的前 limit 根，升序。用于结算重放窗口（P0-2）。"""
        if tf not in _KLINE_TFS:
            raise ValueError(f"未知周期 {tf}")
        return self.conn.execute(
            f"SELECT * FROM kline_{tf} WHERE ts>? ORDER BY ts ASC LIMIT ?",
            (after_ts, limit),
        ).fetchall()

    # --- 快照 ---
    def save_snapshot(self, snapshot_id: str, ts: int, symbol: str,
                      market_state: str | None, payload: dict, data_quality: dict,
                      config_version: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO snapshots "
            "(snapshot_id,ts,symbol,market_state,payload,data_quality,config_version) "
            "VALUES (?,?,?,?,?,?,?)",
            (snapshot_id, ts, symbol, market_state,
             json.dumps(payload, ensure_ascii=False),
             json.dumps(data_quality, ensure_ascii=False), config_version),
        )

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        d["data_quality"] = json.loads(d["data_quality"])
        return d

    # --- 分析结果 ---
    def save_analysis(self, *, ts: int, snapshot_id: str, symbol: str,
                      score: int | None, direction: str | None, plan: dict | None,
                      llm_output: str | None, card_text: str | None,
                      prompt_version: str | None, config_version: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO analyses "
            "(ts,snapshot_id,symbol,score,direction,plan,llm_output,card_text,"
            " prompt_version,config_version) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts, snapshot_id, symbol, score, direction,
             json.dumps(plan, ensure_ascii=False) if plan is not None else None,
             llm_output, card_text, prompt_version, config_version),
        )
        return int(cur.lastrowid)

    def settle_analysis(self, analysis_id: int, *, outcome: str, entry_hit: int,
                        exit_reason: str, settled_ts: int,
                        outcome_note: str | None = None) -> None:
        """结算 job 回填生命周期结果（P0-2）。"""
        self.conn.execute(
            "UPDATE analyses SET outcome=?,entry_hit=?,exit_reason=?,settled_ts=?,"
            "outcome_note=? WHERE id=?",
            (outcome, entry_hit, exit_reason, settled_ts, outcome_note, analysis_id),
        )

    def unsettled_analyses(self, before_ts: int) -> list[sqlite3.Row]:
        """有效期已过但仍未结算的信号（供结算 job 扫描，P0-2）。"""
        return self.conn.execute(
            "SELECT * FROM analyses WHERE outcome IS NULL AND ts<=? ORDER BY ts ASC",
            (before_ts,),
        ).fetchall()

    # --- 信号 / 背景 / 事件 ---
    def save_signal(self, *, ts: int, snapshot_id: str, module: str,
                    direction: str | None, strength: int | None,
                    confidence: str | None, details: dict | None) -> None:
        self.conn.execute(
            "INSERT INTO signals (ts,snapshot_id,module,direction,strength,"
            "confidence,details) VALUES (?,?,?,?,?,?,?)",
            (ts, snapshot_id, module, direction, strength, confidence,
             json.dumps(details, ensure_ascii=False) if details else None),
        )

    # --- 只读连接（给并发读取方，如回测/查询）---
    def connect_readonly(self) -> sqlite3.Connection:
        """只读连接（uri 模式 mode=ro）。读方与单写入者并发安全（WAL）。"""
        uri = f"file:{self.db_path}?mode=ro"
        c = sqlite3.connect(uri, uri=True)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=5000;")
        return c

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
