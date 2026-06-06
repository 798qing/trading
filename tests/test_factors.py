"""oi_funding / basis 因子检测器（P0-①/②）。"""
from types import SimpleNamespace

from detectors.basis import BasisDetector
from detectors.oi_funding import OIFundingDetector


def _snap(make_klines, rows, sources):
    return SimpleNamespace(sources=sources,
                           klines=lambda tf: make_klines(rows))


_FLAT = [(100, 101, 99, 100, 1000.0)] * 10


# ---------------- oi_funding ----------------
def test_price_up_oi_up_is_bullish(dcfg, make_klines):
    rows = [(90 + i, 90 + i + 0.5, 90 + i - 0.5, 90 + i, 1000.0) for i in range(8)]  # 价涨
    snap = _snap(make_klines, rows,
                 {"funding": {"rate": 0.0001}, "oi": {"change_pct": 5.0}})
    r = OIFundingDetector().detect(snap, dcfg)
    assert r.direction == "bullish" and "price_up_oi_up" in r.events


def test_price_down_oi_up_is_bearish(dcfg, make_klines):
    rows = [(100 - i, 100 - i + 0.5, 100 - i - 0.5, 100 - i, 1000.0) for i in range(8)]
    snap = _snap(make_klines, rows,
                 {"funding": {"rate": 0.0001}, "oi": {"change_pct": 5.0}})
    r = OIFundingDetector().detect(snap, dcfg)
    assert r.direction == "bearish" and "price_down_oi_up" in r.events


def test_funding_crowded_long_tilts_bearish(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT, {"funding": {"rate": 0.001}, "oi": {}})
    r = OIFundingDetector().detect(snap, dcfg)
    assert "funding_crowded_long" in r.events


def test_oi_funding_insufficient(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT, {})
    r = OIFundingDetector().detect(snap, dcfg)
    assert r.warnings


# ---------------- basis ----------------
def test_contango_bullish(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT, {"mark": {"price": 100.05}, "spot": {"price": 100.0}})
    r = BasisDetector().detect(snap, dcfg)
    assert r.direction == "bullish" and "contango" in r.events


def test_backwardation_bearish(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT, {"mark": {"price": 99.9}, "spot": {"price": 100.0}})
    r = BasisDetector().detect(snap, dcfg)
    assert r.direction == "bearish" and "backwardation" in r.events


def test_contango_hot_flips_caution(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT, {"mark": {"price": 100.5}, "spot": {"price": 100.0}})
    r = BasisDetector().detect(snap, dcfg)   # 0.5% 升水 → 过热
    assert "contango_hot" in r.events


def test_basis_missing_spot_insufficient(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT, {"mark": {"price": 100.0}})
    r = BasisDetector().detect(snap, dcfg)
    assert r.warnings
