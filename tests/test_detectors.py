"""structure / volume / adx / fib 检测器集成测试（用假快照 + 合成 K 线）。"""
from detectors.adx import ADXDetector
from detectors.fib import FibDetector
from detectors.structure import StructureDetector
from detectors.volume import VolumeDetector

_VALID_DIR = {"bullish", "bearish", "neutral"}
_VALID_CONF = {"high", "medium", "low"}


def _zigzag(pivots, bars_per_leg=7):
    """pivots: 交替的低/高价位序列；线性插值成 K 线 rows(o,h,l,c,v)。"""
    rows = []
    for a, b in zip(pivots, pivots[1:]):
        for j in range(bars_per_leg):
            p = a + (b - a) * j / bars_per_leg
            rows.append((p, p + 0.5, p - 0.5, p, 1000.0))
    return rows


def _assert_schema(r):
    assert r.direction in _VALID_DIR
    assert 1 <= r.strength <= 5
    assert r.confidence in _VALID_CONF


# ---------------- structure ----------------
def test_structure_uptrend_is_bullish(dcfg, make_klines, make_snap):
    # 低/高都抬升：100→120→110→135→125→150
    rows = _zigzag([100, 120, 110, 135, 125, 150])
    snap = make_snap(**{"15m": make_klines(rows)})
    r = StructureDetector().detect(snap, dcfg)
    _assert_schema(r)
    assert r.direction == "bullish"
    assert r.details["structure"] in {"uptrend", "range"} or "breakout_up" in r.events


def test_structure_downtrend_is_bearish(dcfg, make_klines, make_snap):
    rows = _zigzag([150, 130, 140, 115, 125, 100])
    snap = make_snap(**{"15m": make_klines(rows)})
    r = StructureDetector().detect(snap, dcfg)
    _assert_schema(r)
    assert r.direction == "bearish"


def test_structure_insufficient(dcfg, make_klines, make_snap):
    snap = make_snap(**{"15m": make_klines([(100, 101, 99, 100, 1)] * 5)})
    r = StructureDetector().detect(snap, dcfg)
    assert r.warnings and r.direction == "neutral"


# ---------------- volume ----------------
def test_volume_spike_up_is_bullish(dcfg, make_klines, make_snap):
    rows = [(100, 101, 99, 100, 1000.0)] * 20
    rows.append((100, 102, 99, 101.5, 5000.0))     # 末根放量阳线
    snap = make_snap(**{"15m": make_klines(rows)})
    r = VolumeDetector().detect(snap, dcfg)
    _assert_schema(r)
    assert r.details["spike"] is True
    assert r.direction == "bullish"
    assert r.details["breakout_volume_ok"] is True


def test_volume_quiet_is_neutral(dcfg, make_klines, make_snap):
    rows = [(100, 101, 99, 100, 1000.0)] * 25
    snap = make_snap(**{"15m": make_klines(rows)})
    r = VolumeDetector().detect(snap, dcfg)
    assert r.details["spike"] is False
    assert r.direction == "neutral"


# ---------------- adx ----------------
def test_adx_strong_trend(dcfg, make_klines, make_snap):
    rows = [(100 + i, 101 + i, 99 + i, 100 + i, 1000.0) for i in range(40)]
    snap = make_snap(**{"15m": make_klines(rows)})
    r = ADXDetector().detect(snap, dcfg)
    _assert_schema(r)
    assert r.direction == "neutral"                 # ADX 不给方向
    assert r.details["classification"] == "strong"


def test_adx_flat_no_trend(dcfg, make_klines, make_snap):
    rows = [(100, 101, 99, 100, 1000.0)] * 40
    snap = make_snap(**{"15m": make_klines(rows)})
    r = ADXDetector().detect(snap, dcfg)
    assert r.details["classification"] == "no_trend"


# ---------------- fib ----------------
def test_fib_at_level_flags_key(dcfg, make_klines, make_snap):
    # 内部 swing 低 100、swing 高 200（上行腿），0.5 回撤位=150；末根收在 150
    rows = _zigzag([120, 100, 200, 150], bars_per_leg=10)
    rows += [(150, 150.2, 149.8, 150.0, 1000.0)]    # 收在 0.5 回撤位
    snap = make_snap(**{"15m": make_klines(rows)})
    r = FibDetector().detect(snap, dcfg)
    _assert_schema(r)
    assert "ret_0.5" in r.details["levels"]
    assert r.details["levels"]["ret_0.5"] == 150.0
    assert r.details["at_key_level"] is True        # 价格正落在 0.5 位
