"""CoinGlass V4 数据采集（阶段2：多空比 / ETF flow 背景）。

只封装公开数据 API，不触碰交易接口。调用方注入 API key（secrets.env:
COINGLASS_API_KEY），测试中可注入 httpx.Client + MockTransport。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

COINGLASS_BASE_URL = "https://open-api-v4.coinglass.com"


class CoinGlassError(RuntimeError):
    """CoinGlass 网络、鉴权、业务码或解析错误。"""


@dataclass(frozen=True)
class LongShortRatio:
    ts: int
    symbol: str
    long_ratio: float | None
    short_ratio: float | None
    long_short_ratio: float | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class ETFFlow:
    ts: int
    ticker: str
    net_flow_usd: float | None
    total_value_usd: float | None
    raw: dict[str, Any]


class CoinGlassClient:
    def __init__(self, api_key: str | None = None, base_url: str = COINGLASS_BASE_URL,
                 timeout: float = 10.0, client: httpx.Client | None = None):
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self._own_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise CoinGlassError("缺少 COINGLASS_API_KEY")
        try:
            self.api_key.encode("ascii")
        except UnicodeEncodeError as e:
            raise CoinGlassError(
                "COINGLASS_API_KEY 含非 ASCII 字符，请检查 secrets.env 是否混入中文注释/括号"
            ) from e
        return {"CG-API-KEY": self.api_key}

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            resp = self._client.get(self.base_url + path, params=params,
                                    headers=self._headers())
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise CoinGlassError(f"CoinGlass 请求失败 {path}: {e}") from e

        code = body.get("code")
        if code not in (0, "0", None):
            raise CoinGlassError(f"CoinGlass 业务错误 {path}: code={code} "
                                 f"msg={body.get('msg')}")
        return body.get("data", body)

    def long_short_ratio(self, *, exchange: str = "OKX", symbol: str = "BTCUSDT",
                         interval: str = "1h", limit: int = 24) -> list[LongShortRatio]:
        """全市场/交易所账户多空比。

        返回按 ts 升序排列。CoinGlass V4 不同端点的 data 可能是 list，也可能包一层
        {"list": [...]}; 这里对两种常见形状做兼容。
        """
        data = self._get("/api/futures/long-short-account-ratio/history",
                         {"exchange": exchange, "symbol": symbol, "interval": interval,
                          "limit": limit})
        rows = _as_rows(data)
        out = [
            LongShortRatio(
                ts=_ts(row),
                symbol=str(row.get("symbol") or symbol),
                long_ratio=_float(row, "longAccount", "long_ratio", "longRate"),
                short_ratio=_float(row, "shortAccount", "short_ratio", "shortRate"),
                long_short_ratio=_float(row, "longShortRatio", "ratio"),
                raw=row,
            )
            for row in rows
        ]
        return sorted(out, key=lambda r: r.ts)

    def bitcoin_etf_flows(self, *, ticker: str = "IBIT", limit: int = 30) -> list[ETFFlow]:
        """BTC ETF 单标的资金流背景数据。

        ETF flow 当前只作为 background，尚未进 fusion 主评分。
        """
        data = self._get("/api/etf/bitcoin/flow-history",
                         {"ticker": ticker, "limit": limit})
        rows = _as_rows(data)
        out = [
            ETFFlow(
                ts=_ts(row),
                ticker=str(row.get("ticker") or row.get("symbol") or ticker),
                net_flow_usd=_float(row, "netFlow", "net_flow", "netInflow"),
                total_value_usd=_float(row, "totalValue", "total_value", "aum"),
                raw=row,
            )
            for row in rows
        ]
        return sorted(out, key=lambda r: r.ts)

    def close(self) -> None:
        if self._own_client:
            self._client.close()

    def __enter__(self) -> "CoinGlassClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _as_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("list", "data", "rows", "items"):
            val = data.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
    raise CoinGlassError("CoinGlass 响应缺少列表数据")


def _float(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        val = row.get(key)
        if val is not None and val != "":
            return float(val)
    return None


def _ts(row: dict[str, Any]) -> int:
    for key in ("time", "ts", "timestamp", "date"):
        val = row.get(key)
        if val is None or val == "":
            continue
        n = int(float(val))
        return n // 1000 if n > 10_000_000_000 else n
    raise CoinGlassError("CoinGlass 行缺少时间字段")
