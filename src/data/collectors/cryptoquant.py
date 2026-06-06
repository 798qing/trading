"""CryptoQuant Data API 采集（阶段2：交易所净流背景）。

封装 exchange-flows/netflow 指标。调用方注入 API key（secrets.env:
CRYPTOQUANT_API_KEY），测试中可注入 httpx.Client + MockTransport。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

CRYPTOQUANT_BASE_URL = "https://api.cryptoquant.com/v1"


class CryptoQuantError(RuntimeError):
    """CryptoQuant 网络、鉴权、业务码或解析错误。"""


@dataclass(frozen=True)
class ExchangeNetflow:
    ts: int
    exchange: str
    window: str
    netflow_total: float | None
    inflow_total: float | None
    outflow_total: float | None
    raw: dict[str, Any]


class CryptoQuantClient:
    def __init__(self, api_key: str | None = None,
                 base_url: str = CRYPTOQUANT_BASE_URL, timeout: float = 10.0,
                 client: httpx.Client | None = None):
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self._own_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise CryptoQuantError("缺少 CRYPTOQUANT_API_KEY")
        return {"Authorization": f"Bearer {self.api_key}"}

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            resp = self._client.get(self.base_url + path, params=params,
                                    headers=self._headers())
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise CryptoQuantError(f"CryptoQuant 请求失败 {path}: {e}") from e

        status = body.get("status")
        if status not in (None, "success", 200, "200"):
            raise CryptoQuantError(f"CryptoQuant 业务错误 {path}: status={status} "
                                   f"msg={body.get('message')}")
        return body.get("result", body.get("data", body))

    def exchange_netflow(self, *, exchange: str = "all_exchange",
                         window: str = "day", limit: int = 30
                         ) -> list[ExchangeNetflow]:
        """BTC 交易所净流入/流出，返回按 ts 升序排列。"""
        data = self._get("/btc/exchange-flows/netflow",
                         {"exchange": exchange, "window": window, "limit": limit})
        rows = _as_rows(data)
        out = [
            ExchangeNetflow(
                ts=_ts(row),
                exchange=str(row.get("exchange") or exchange),
                window=str(row.get("window") or window),
                netflow_total=_float(row, "netflow_total", "netflow", "net_flow_total"),
                inflow_total=_float(row, "inflow_total", "inflow", "inflow_total_usd"),
                outflow_total=_float(row, "outflow_total", "outflow", "outflow_total_usd"),
                raw=row,
            )
            for row in rows
        ]
        return sorted(out, key=lambda r: r.ts)

    def close(self) -> None:
        if self._own_client:
            self._client.close()

    def __enter__(self) -> "CryptoQuantClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _as_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("data", "list", "rows", "items"):
            val = data.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
    raise CryptoQuantError("CryptoQuant 响应缺少列表数据")


def _float(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        val = row.get(key)
        if val is not None and val != "":
            return float(val)
    return None


def _ts(row: dict[str, Any]) -> int:
    for key in ("time", "ts", "timestamp"):
        val = row.get(key)
        if val is None or val == "":
            continue
        n = int(float(val))
        return n // 1000 if n > 10_000_000_000 else n

    for key in ("date", "datetime"):
        val = row.get(key)
        if not val:
            continue
        text = str(val).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    raise CryptoQuantError("CryptoQuant 行缺少时间字段")
