"""宏观联动采集：BTC 与 Nasdaq / DXY 的滚动相关。

使用 Yahoo Finance 公开 chart 接口，无需 API key。该源只作为阶段3背景因子；
网络失败、数据不足或接口变形时由调用方降级为 unavailable。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

YAHOO_CHART_BASE_URL = "https://query1.finance.yahoo.com"


class MacroDataError(RuntimeError):
    """宏观行情网络、业务或解析错误。"""


@dataclass(frozen=True)
class MacroSnapshot:
    as_of_ts: int
    risk_state: str
    btc_nasdaq_corr: float | None
    btc_dxy_corr: float | None
    nasdaq_symbol: str
    dxy_symbol: str
    event_in_window: bool = False
    event_name: str | None = None


class YahooMacroClient:
    def __init__(self, base_url: str = YAHOO_CHART_BASE_URL, timeout: float = 10.0,
                 client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self._own_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def daily_closes(self, symbol: str, *, range_: str = "120d"
                     ) -> list[tuple[int, float]]:
        path = f"/v8/finance/chart/{quote(symbol, safe='')}"
        try:
            resp = self._client.get(
                self.base_url + path,
                params={"range": range_, "interval": "1d"},
                headers={"User-Agent": "trading-agent/1.0"},
            )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise MacroDataError(f"Yahoo 请求失败 {symbol}: {e}") from e

        try:
            result = (body.get("chart") or {}).get("result") or []
            if not result:
                err = (body.get("chart") or {}).get("error")
                raise MacroDataError(f"Yahoo 无结果 {symbol}: {err}")
            item = result[0]
            timestamps = item.get("timestamp") or []
            quote0 = ((item.get("indicators") or {}).get("quote") or [{}])[0]
            closes = quote0.get("close") or []
        except (AttributeError, IndexError) as e:
            raise MacroDataError(f"Yahoo 响应结构异常 {symbol}") from e

        rows: list[tuple[int, float]] = []
        for ts, close in zip(timestamps, closes):
            if ts is None or close is None:
                continue
            rows.append((int(ts), float(close)))
        rows.sort(key=lambda r: r[0])
        if len(rows) < 2:
            raise MacroDataError(f"Yahoo {symbol} 收盘价不足")
        return rows

    def rolling_linkage(self, *, btc_symbol: str = "BTC-USD",
                        nasdaq_symbol: str = "^IXIC",
                        dxy_symbol: str = "DX-Y.NYB",
                        window_days: int = 30,
                        min_overlap: int = 20) -> MacroSnapshot:
        btc = self.daily_closes(btc_symbol)
        nasdaq = self.daily_closes(nasdaq_symbol)
        dxy = self.daily_closes(dxy_symbol)

        btc_nasdaq_corr, nasdaq_ret = _corr_and_peer_return(
            btc, nasdaq, window_days=window_days, min_overlap=min_overlap,
        )
        btc_dxy_corr, dxy_ret = _corr_and_peer_return(
            btc, dxy, window_days=window_days, min_overlap=min_overlap,
        )

        risk_state = _risk_state(
            btc_nasdaq_corr=btc_nasdaq_corr,
            btc_dxy_corr=btc_dxy_corr,
            nasdaq_return=nasdaq_ret,
            dxy_return=dxy_ret,
        )
        as_of_ts = max(btc[-1][0], nasdaq[-1][0], dxy[-1][0])
        return MacroSnapshot(
            as_of_ts=as_of_ts,
            risk_state=risk_state,
            btc_nasdaq_corr=btc_nasdaq_corr,
            btc_dxy_corr=btc_dxy_corr,
            nasdaq_symbol=nasdaq_symbol,
            dxy_symbol=dxy_symbol,
        )

    def close(self) -> None:
        if self._own_client:
            self._client.close()

    def __enter__(self) -> "YahooMacroClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _corr_and_peer_return(left: list[tuple[int, float]], right: list[tuple[int, float]],
                          *, window_days: int, min_overlap: int
                          ) -> tuple[float | None, float | None]:
    left_by_day = {_day(ts): close for ts, close in left}
    right_by_day = {_day(ts): close for ts, close in right}
    days = sorted(set(left_by_day) & set(right_by_day))
    if len(days) < min_overlap + 1:
        return None, None

    left_returns: list[float] = []
    right_returns: list[float] = []
    for prev, cur in zip(days, days[1:]):
        lp, lc = left_by_day[prev], left_by_day[cur]
        rp, rc = right_by_day[prev], right_by_day[cur]
        if lp <= 0 or rp <= 0:
            continue
        left_returns.append((lc - lp) / lp)
        right_returns.append((rc - rp) / rp)

    if len(left_returns) < min_overlap:
        return None, None
    left_window = left_returns[-window_days:]
    right_window = right_returns[-window_days:]
    if len(left_window) < min_overlap:
        return None, None

    peer_return = right_window[-1] if right_window else None
    corr = _pearson(left_window, right_window)
    return (round(corr, 4) if corr is not None else None), peer_return


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / (vx ** 0.5 * vy ** 0.5)


def _risk_state(*, btc_nasdaq_corr: float | None, btc_dxy_corr: float | None,
                nasdaq_return: float | None, dxy_return: float | None) -> str:
    score = 0
    if btc_nasdaq_corr is not None and btc_nasdaq_corr >= 0.25:
        if nasdaq_return is not None and nasdaq_return > 0:
            score += 1
        elif nasdaq_return is not None and nasdaq_return < 0:
            score -= 1
    if btc_dxy_corr is not None and btc_dxy_corr <= -0.20:
        if dxy_return is not None and dxy_return < 0:
            score += 1
        elif dxy_return is not None and dxy_return > 0:
            score -= 1
    if score > 0:
        return "risk_on"
    if score < 0:
        return "risk_off"
    return "neutral"


def _day(ts: int) -> int:
    return int(ts) // 86_400


def snapshot_to_source(s: MacroSnapshot) -> dict[str, Any]:
    return {
        "risk_state": s.risk_state,
        "btc_nasdaq_corr": s.btc_nasdaq_corr,
        "btc_dxy_corr": s.btc_dxy_corr,
        "event_in_window": s.event_in_window,
        "event_name": s.event_name,
        "nasdaq_symbol": s.nasdaq_symbol,
        "dxy_symbol": s.dxy_symbol,
        "as_of_ts": s.as_of_ts,
    }
