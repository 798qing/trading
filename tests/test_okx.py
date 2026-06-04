"""okx.py — 公开行情采集，离线 mock（httpx.MockTransport），不连真网。"""
import httpx
import pytest

from data.collectors.okx import OKXClient, OKXError


def _client(handler):
    transport = httpx.MockTransport(handler)
    return OKXClient(client=httpx.Client(transport=transport))


def test_candles_keeps_only_closed_and_sorts_ascending():
    # 返回 3 根：最新一根 confirm=0（未收线），应被丢弃；其余按 ts 升序
    def handler(req):
        return httpx.Response(200, json={"code": "0", "msg": "", "data": [
            ["1700000900000", "11", "13", "10", "12", "80", "0", "0", "0"],  # 未收线
            ["1700000000000", "10", "12", "9", "11", "100", "0", "0", "1"],  # 已收线
            ["1699999100000", "9", "11", "8", "10", "60", "0", "0", "1"],    # 已收线（更早）
        ]})
    rows = _client(handler).candles("BTC-USDT-SWAP", "15m", limit=3)
    assert len(rows) == 2                      # 未收线那根被丢弃
    assert [r[0] for r in rows] == [1699999100, 1700000000]  # 升序、ms→s
    assert rows[1] == (1700000000, 10.0, 12.0, 9.0, 11.0, 100.0)


def test_candles_rejects_unknown_bar():
    with pytest.raises(OKXError):
        _client(lambda req: httpx.Response(200, json={"code": "0", "data": []})) \
            .candles("BTC-USDT-SWAP", "7m")


def test_nonzero_code_raises():
    def handler(req):
        return httpx.Response(200, json={"code": "51001", "msg": "bad instId",
                                         "data": []})
    with pytest.raises(OKXError, match="51001"):
        _client(handler).candles("X", "15m")


def test_http_error_wrapped():
    def handler(req):
        return httpx.Response(500, json={})
    with pytest.raises(OKXError):
        _client(handler).mark_price("BTC-USDT-SWAP")


def test_mark_price_parsing():
    def handler(req):
        return httpx.Response(200, json={"code": "0", "data": [
            {"instId": "BTC-USDT-SWAP", "markPx": "67250.5", "ts": "1700000000500"}]})
    mp = _client(handler).mark_price("BTC-USDT-SWAP")
    assert mp.price == 67250.5 and mp.as_of_ts == 1700000000


def test_funding_rate_parsing():
    def handler(req):
        return httpx.Response(200, json={"code": "0", "data": [
            {"fundingRate": "0.0001", "nextFundingTime": "1700028800000",
             "ts": "1700000000000"}]})
    fr = _client(handler).funding_rate("BTC-USDT-SWAP")
    assert fr.rate == 0.0001 and fr.next_funding_ts == 1700028800


def test_open_interest_parsing():
    def handler(req):
        return httpx.Response(200, json={"code": "0", "data": [
            {"oi": "123456", "oiCcy": "789.0", "ts": "1700000000000"}]})
    oi = _client(handler).open_interest("BTC-USDT-SWAP")
    assert oi.oi == 123456.0 and oi.oi_ccy == 789.0
