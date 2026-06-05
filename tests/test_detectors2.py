"""candle / macd / rsi 检测器测试。"""
from detectors.candle import CandleDetector
from detectors.macd import MACDDetector
from detectors.rsi import RSIDetector

_VALID_DIR = {"bullish", "bearish", "neutral"}


def _schema(r):
    assert r.direction in _VALID_DIR
    assert 1 <= r.strength <= 5
    assert r.confidence in {"high", "medium", "low"}


# ---------------- macd ----------------
def test_macd_golden_cross_bullish(dcfg, make_klines, make_snap):
    # 先跌后强涨 → DIF 上穿 DEA → 金叉
    rows = [(100 - i, 100 - i + 0.5, 100 - i - 0.5, 100 - i, 1000.0) for i in range(40)]
    rows += [(60 + i * 2, 60 + i * 2 + 0.5, 60 + i * 2 - 0.5, 60 + i * 2, 1000.0)
             for i in range(20)]
    r = MACDDetector().detect(make_snap(**{"15m": make_klines(rows)}), dcfg)
    _schema(r)
    assert r.direction == "bullish"


def test_macd_insufficient(dcfg, make_klines, make_snap):
    r = MACDDetector().detect(make_snap(**{"15m": make_klines([(100, 101, 99, 100, 1)] * 10)}), dcfg)
    assert r.warnings and r.direction == "neutral"


# ---------------- rsi ----------------
def test_rsi_oversold_bullish(dcfg, make_klines, make_snap):
    # 持续下跌 → RSI 低 → 超卖偏多
    rows = [(100 - i, 100 - i + 0.3, 100 - i - 0.3, 100 - i, 1000.0) for i in range(30)]
    r = RSIDetector().detect(make_snap(**{"15m": make_klines(rows)}), dcfg)
    _schema(r)
    assert "oversold" in r.events and r.direction == "bullish"


def test_rsi_overbought_bearish(dcfg, make_klines, make_snap):
    rows = [(100 + i, 100 + i + 0.3, 100 + i - 0.3, 100 + i, 1000.0) for i in range(30)]
    r = RSIDetector().detect(make_snap(**{"15m": make_klines(rows)}), dcfg)
    assert "overbought" in r.events and r.direction == "bearish"


# ---------------- candle ----------------
def test_candle_bullish_engulfing(dcfg, make_klines, make_snap):
    rows = [(100, 101, 99, 100, 1000.0)] * 3
    rows += [(100, 100.2, 98, 98.5, 1000.0)]      # 阴线
    rows += [(98, 101.5, 97.8, 101, 1000.0)]      # 阳线吞没前一根
    r = CandleDetector().detect(make_snap(**{"15m": make_klines(rows)}), dcfg)
    _schema(r)
    assert r.details["pattern"] == "bullish_engulfing" and r.direction == "bullish"


def test_candle_hammer_needs_confirmation(dcfg, make_klines, make_snap):
    rows = [(100, 101, 99, 100, 1000.0)] * 3
    rows += [(100, 100.15, 95, 100.1, 1000.0)]    # 长下影、上影极小、实体小 → 锤子
    r = CandleDetector().detect(make_snap(**{"15m": make_klines(rows)}), dcfg)
    assert r.details["pattern"] == "hammer"
    assert r.details["needs_confirmation"] is True


def test_candle_insufficient(dcfg, make_klines, make_snap):
    r = CandleDetector().detect(make_snap(**{"15m": make_klines([(100, 101, 99, 100, 1)] * 2)}), dcfg)
    assert r.warnings
