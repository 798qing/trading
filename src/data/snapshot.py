"""market_snapshot：冻结一次分析的全部输入（D6）。

核心约定：每次分析固化为一个 snapshot_id，检测器/聚合/计划/回测都引用同一份，
不允许各自单独取数 → 杜绝时间穿越（look-ahead）。
- K 线按各周期 last_closed 边界裁剪并冻结进内存（D7：只用已收线）。
- 每个外部源记录 as_of_ts 与 status，新鲜度可混用但必须显式标注。
- 快照带 config_version（P0-4），回测重放历史快照而非重新拉数。

分工：
- build_snapshot()  纯内存、不联网、可离线测。
- collect_and_freeze()  联网编排：拉数写库 → build_snapshot。
"""
from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass, field
from typing import Any

from common import clock
from common.config import Config
from data.store import Store

Kline = namedtuple("Kline", "ts open high low close volume")

# 单周期可做分析的最小根数（不足则 data_quality 告警；区别于 config 的 min_klines 目标值）
_MIN_ROWS_FOR_ANALYSIS = 50

# 各源新鲜度阈值（秒）：超过则标 stale。资金费率本就低频，给宽容窗口。
_STALE_THRESHOLD = {"mark": 120, "oi": 300, "funding": 3 * 3600, "spot": 120}


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    symbol: str
    analysis_ts: int                 # = primary 周期最近已收线 ts
    config_version: str
    timeframes: dict[str, dict]      # tf -> {last_closed_kline_ts, rows}
    sources: dict[str, dict]         # name -> {as_of_ts, status, ...value}
    data_quality: dict[str, Any]
    _klines: dict[str, list] = field(default_factory=dict, repr=False)

    def klines(self, tf: str) -> list[Kline]:
        """冻结的已收线 K 线（升序）。下游只能从这里取，保证可重放。"""
        return self._klines.get(tf, [])

    def last_close(self, tf: str) -> float | None:
        ks = self._klines.get(tf)
        return ks[-1].close if ks else None


def _source_status(value: dict | None, kind: str, now: int) -> str:
    if not value:
        return "unavailable"
    as_of = value.get("as_of_ts") or 0
    if as_of <= 0:
        return "stale"
    return "fresh" if (now - as_of) <= _STALE_THRESHOLD[kind] else "stale"


def _snapshot_id(symbol: str, analysis_ts: int) -> str:
    base = symbol.split("-")[0].lower()           # BTC-USDT-SWAP -> btc
    stamp = clock.from_ts(analysis_ts).strftime("%Y%m%d_%H%M%S")
    return f"{base}_{stamp}"


def build_snapshot(store: Store, cfg: Config, aux: dict[str, dict | None],
                   now: int | None = None, persist: bool = True) -> Snapshot:
    """从已写库的 K 线 + 即时辅助数据(aux) 冻结一个快照。

    aux 形如 {"mark": {...,"as_of_ts"}, "funding": {...}, "oi": {...}}，
    缺某项传 None，对应 source.status=unavailable。
    """
    n = clock.now_ts() if now is None else now
    symbol = cfg.require("meta.symbol")
    tfs: list[str] = cfg.require("timeframes.all")
    primary: str = cfg.require("timeframes.primary")
    higher: list[str] = cfg.get("timeframes.higher", [])
    target_rows: int = cfg.get("timeframes.min_klines", 300)

    analysis_ts = clock.last_closed_ts(primary, now=n)

    klines: dict[str, list] = {}
    timeframes: dict[str, dict] = {}
    warnings: list[str] = []

    for tf in tfs:
        bound = clock.last_closed_ts(tf, now=n)
        rows = store.klines(tf, limit=target_rows, before_ts=bound)
        ks = [Kline(r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"])
              for r in rows]
        klines[tf] = ks
        timeframes[tf] = {
            "last_closed_kline_ts": ks[-1].ts if ks else None,
            "rows": len(ks),
        }
        if tf in ([primary] + list(higher)) and len(ks) < _MIN_ROWS_FOR_ANALYSIS:
            warnings.append(f"{tf} 仅 {len(ks)} 根，不足 {_MIN_ROWS_FOR_ANALYSIS}")

    # OI 环比变化（price×OI 组合用）：与上一份快照比
    if aux.get("oi"):
        prior = _prior_oi(store)
        if prior and prior > 0:
            aux["oi"]["change_pct"] = round((aux["oi"]["oi"] - prior) / prior * 100, 4)

    # 外部即时源（spot 为可选，缺失不视为不完整）
    sources: dict[str, dict] = {}
    for kind in ("mark", "funding", "oi", "spot"):
        val = aux.get(kind)
        status = _source_status(val, kind, n)
        entry = {"status": status}
        if val:
            entry.update(val)
        sources[kind] = entry
        if status == "stale":
            warnings.append(f"{kind} 数据过期（as_of={val.get('as_of_ts') if val else None}）")
        elif status == "unavailable" and kind != "spot":
            warnings.append(f"{kind} 数据不可用")

    required = [primary] + list(higher)
    is_complete = all(timeframes[tf]["rows"] >= _MIN_ROWS_FOR_ANALYSIS
                      for tf in required) and sources["mark"]["status"] != "unavailable"
    data_quality = {
        "is_complete": is_complete,
        "has_stale_source": any(s["status"] == "stale" for s in sources.values()),
        "warnings": warnings,
    }

    snap = Snapshot(
        snapshot_id=_snapshot_id(symbol, analysis_ts),
        symbol=symbol,
        analysis_ts=analysis_ts,
        config_version=cfg.version,
        timeframes=timeframes,
        sources=sources,
        data_quality=data_quality,
        _klines=klines,
    )

    if persist:
        store.save_snapshot(
            snapshot_id=snap.snapshot_id, ts=snap.analysis_ts, symbol=symbol,
            market_state=None,                       # 由检测层后填
            payload={"timeframes": timeframes, "sources": sources},
            data_quality=data_quality, config_version=cfg.version,
        )
    return snap


def latest_sources(store: Store) -> dict[str, dict | None]:
    """从最近一条已存快照取回外部源（作为热路径重算的 aux）。

    让 /btc 能用 precompute 落库的最新外部数据重建快照，而不必再 live 拉 OKX。
    无历史快照时各项返回 None。
    """
    row = store.conn.execute(
        "SELECT payload FROM snapshots ORDER BY ts DESC LIMIT 1").fetchone()
    kinds = ("mark", "funding", "oi", "spot")
    if not row:
        return {kind: None for kind in kinds}
    import json as _json
    sources = _json.loads(row["payload"]).get("sources", {})
    out: dict[str, dict | None] = {}
    for kind in kinds:
        val = sources.get(kind)
        # 仅在有真实数据时回填（status=unavailable 视为无）
        out[kind] = val if val and val.get("status") != "unavailable" else None
    return out


def _prior_oi(store: Store) -> float | None:
    """上一份快照记录的 OI（算环比变化用）。"""
    src = latest_sources(store).get("oi")
    return src.get("oi") if src else None


def has_klines(store: Store, tf: str, min_rows: int = _MIN_ROWS_FOR_ANALYSIS) -> bool:
    """库里某周期是否已有足够 K 线（判断要不要先 live 采集）。"""
    n = store.conn.execute(f"SELECT COUNT(*) FROM kline_{tf}").fetchone()[0]
    return n >= min_rows


def collect_and_freeze(store: Store, cfg: Config, okx, now: int | None = None
                       ) -> Snapshot:
    """联网编排：拉 OKX K线/标记价/费率/OI → 写库 → 冻结快照。

    okx 为 OKXClient 实例（依赖注入，便于测试时替换）。
    """
    symbol = cfg.require("meta.symbol")
    target_rows = cfg.get("timeframes.min_klines", 300)
    for tf in cfg.require("timeframes.all"):
        rows = okx.candles(symbol, tf, limit=target_rows)
        if rows:
            store.upsert_klines(tf, rows)

    aux: dict[str, dict | None] = {}
    try:
        mp = okx.mark_price(symbol)
        aux["mark"] = {"price": mp.price, "as_of_ts": mp.as_of_ts}
    except Exception:
        aux["mark"] = None
    try:
        fr = okx.funding_rate(symbol)
        aux["funding"] = {"rate": fr.rate, "next_funding_ts": fr.next_funding_ts,
                          "as_of_ts": fr.as_of_ts}
    except Exception:
        aux["funding"] = None
    try:
        oi = okx.open_interest(symbol)
        aux["oi"] = {"oi": oi.oi, "oi_ccy": oi.oi_ccy, "as_of_ts": oi.as_of_ts}
    except Exception:
        aux["oi"] = None
    try:                                       # 现货价（期现基差用）：BTC-USDT-SWAP → BTC-USDT
        spot_inst = symbol.replace("-SWAP", "")
        sp = okx.ticker_last(spot_inst)
        aux["spot"] = {"price": sp.price, "as_of_ts": sp.as_of_ts}
    except Exception:
        aux["spot"] = None

    return build_snapshot(store, cfg, aux, now=now)
