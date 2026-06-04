"""OKX v5 公开行情采集（免 API key）。

只用公开接口：K线 / 标记价 / 资金费率 / OI（均为全市场公共数据，无账户成分，
不需鉴权，按 IP 限流）。本系统纯分析不下单（D1），永不触碰私有/交易接口。

防前视（D7）：K线只返回 confirm==1 的**已收线**那几根，正在形成的当根丢弃。
时间一律转为 UTC epoch 秒（D8）。

可注入 httpx.Client（构造参数 client）以便离线 mock 测试。
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

OKX_BASE_URL = "https://www.okx.com"

# 周期 → OKX bar 参数（注意 OKX 用大写 H/D）
_BAR_MAP: dict[str, str] = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "4h": "4H", "1d": "1D",
}


class OKXError(RuntimeError):
    """OKX 返回非 0 code 或网络/解析异常。"""


@dataclass
class FundingRate:
    rate: float
    next_funding_ts: int | None  # 下次结算时间（UTC 秒）
    as_of_ts: int


@dataclass
class OpenInterest:
    oi: float          # 张数
    oi_ccy: float      # 折合币
    as_of_ts: int


@dataclass
class MarkPrice:
    price: float
    as_of_ts: int


class OKXClient:
    def __init__(self, base_url: str = OKX_BASE_URL, timeout: float = 10.0,
                 client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self._own_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    # --- 内部 ---
    def _get(self, path: str, params: dict) -> list[dict]:
        try:
            resp = self._client.get(self.base_url + path, params=params)
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise OKXError(f"OKX 请求失败 {path}: {e}") from e
        if body.get("code") != "0":
            raise OKXError(f"OKX 业务错误 {path}: code={body.get('code')} "
                           f"msg={body.get('msg')}")
        return body.get("data", [])

    # --- K 线（只取已收线，D7）---
    def candles(self, inst_id: str, bar: str, limit: int = 300
                ) -> list[tuple[int, float, float, float, float, float]]:
        """返回 [(ts_sec, open, high, low, close, volume), ...]，按 ts 升序。

        仅包含 confirm==1（已收线）的 K 线，正在形成的当根被丢弃。
        ts 为开盘时间，单位秒（OKX 原始为毫秒）。
        """
        if bar not in _BAR_MAP:
            raise OKXError(f"未知周期 {bar}，允许 {list(_BAR_MAP)}")
        data = self._get("/api/v5/market/candles",
                         {"instId": inst_id, "bar": _BAR_MAP[bar], "limit": str(limit)})
        rows: list[tuple[int, float, float, float, float, float]] = []
        for c in data:
            # OKX 行：[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
            if len(c) < 9 or c[8] != "1":      # 只要已收线
                continue
            rows.append((
                int(c[0]) // 1000,             # ms → s
                float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5]),
            ))
        rows.sort(key=lambda r: r[0])          # 升序
        return rows

    # --- 标记价 ---
    def mark_price(self, inst_id: str) -> MarkPrice:
        data = self._get("/api/v5/public/mark-price",
                         {"instType": "SWAP", "instId": inst_id})
        if not data:
            raise OKXError(f"标记价为空：{inst_id}")
        d = data[0]
        return MarkPrice(price=float(d["markPx"]), as_of_ts=int(d["ts"]) // 1000)

    # --- 资金费率 ---
    def funding_rate(self, inst_id: str) -> FundingRate:
        data = self._get("/api/v5/public/funding-rate", {"instId": inst_id})
        if not data:
            raise OKXError(f"资金费率为空：{inst_id}")
        d = data[0]
        nxt = d.get("nextFundingTime") or d.get("fundingTime")
        return FundingRate(
            rate=float(d["fundingRate"]),
            next_funding_ts=int(nxt) // 1000 if nxt else None,
            as_of_ts=int(d.get("ts", "0") or "0") // 1000 or 0,
        )

    # --- 未平仓量 OI ---
    def open_interest(self, inst_id: str) -> OpenInterest:
        data = self._get("/api/v5/public/open-interest",
                         {"instType": "SWAP", "instId": inst_id})
        if not data:
            raise OKXError(f"OI 为空：{inst_id}")
        d = data[0]
        return OpenInterest(
            oi=float(d["oi"]), oi_ccy=float(d.get("oiCcy", 0) or 0),
            as_of_ts=int(d["ts"]) // 1000,
        )

    def close(self) -> None:
        if self._own_client:
            self._client.close()

    def __enter__(self) -> "OKXClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
