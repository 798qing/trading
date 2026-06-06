"""CoinGlass / CryptoQuant collectors：离线 mock，不连真网。"""
import httpx
import pytest

from data.collectors.coinglass import CoinGlassClient, CoinGlassError
from data.collectors.cryptoquant import CryptoQuantClient, CryptoQuantError


def _http(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_coinglass_long_short_ratio_parsing_and_headers():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["key"] = req.headers.get("CG-API-KEY")
        return httpx.Response(200, json={"code": "0", "data": {"list": [
            {"time": 1700003600000, "symbol": "BTCUSDT", "longAccount": "0.61",
             "shortAccount": "0.39", "longShortRatio": "1.56"},
            {"time": 1700000000000, "symbol": "BTCUSDT", "longAccount": "0.58",
             "shortAccount": "0.42", "longShortRatio": "1.38"},
        ]}})

    c = CoinGlassClient(api_key="cg-key", client=_http(handler))
    rows = c.long_short_ratio(exchange="OKX", symbol="BTCUSDT", interval="1h", limit=2)

    assert seen["path"] == "/api/futures/long-short-account-ratio/history"
    assert seen["key"] == "cg-key"
    assert [r.ts for r in rows] == [1700000000, 1700003600]
    assert rows[-1].long_ratio == 0.61
    assert rows[-1].long_short_ratio == 1.56


def test_coinglass_rejects_missing_key():
    c = CoinGlassClient(client=_http(lambda req: httpx.Response(200, json={})))
    with pytest.raises(CoinGlassError, match="COINGLASS_API_KEY"):
        c.long_short_ratio()


def test_coinglass_etf_flow_parsing():
    def handler(req):
        return httpx.Response(200, json={"code": 0, "data": [
            {"date": 1700000000, "ticker": "IBIT", "netFlow": "12500000",
             "totalValue": "1000000000"}
        ]})

    rows = CoinGlassClient(api_key="cg-key", client=_http(handler)) \
        .bitcoin_etf_flows(ticker="IBIT", limit=1)
    assert rows[0].ticker == "IBIT"
    assert rows[0].net_flow_usd == 12_500_000.0


def test_cryptoquant_exchange_netflow_parsing_and_headers():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["auth"] = req.headers.get("Authorization")
        return httpx.Response(200, json={"status": "success", "result": {"data": [
            {"date": "2026-06-05", "exchange": "all_exchange",
             "netflow_total": "-123.4", "inflow_total": "1000", "outflow_total": "1123.4"}
        ]}})

    rows = CryptoQuantClient(api_key="cq-key", client=_http(handler)) \
        .exchange_netflow(limit=1)

    assert seen["path"] == "/v1/btc/exchange-flows/netflow"
    assert seen["auth"] == "Bearer cq-key"
    assert rows[0].ts == 1780617600
    assert rows[0].netflow_total == -123.4
    assert rows[0].outflow_total == 1123.4


def test_cryptoquant_rejects_missing_key():
    c = CryptoQuantClient(client=_http(lambda req: httpx.Response(200, json={})))
    with pytest.raises(CryptoQuantError, match="CRYPTOQUANT_API_KEY"):
        c.exchange_netflow()
