"""oi_funding / basis 因子检测器（P0-①/②）。"""
from types import SimpleNamespace

from detectors.basis import BasisDetector
from detectors.liquidation import LiquidationDetector
from detectors.macro import MacroDetector
from detectors.oi_funding import OIFundingDetector
from detectors.onchain import OnchainDetector
from detectors.vol_regime import VolRegimeDetector


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


# ---------------- stage3 external factors ----------------
def test_liquidation_long_crowding_tilts_bearish(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT,
                 {"long_short": {"long_ratio": 0.66, "short_ratio": 0.34,
                                  "long_short_ratio": 1.94, "status": "fresh"}})
    r = LiquidationDetector().detect(snap, dcfg)
    assert r.direction == "bearish"
    assert "long_crowding" in r.events


def test_liquidation_missing_source_is_neutral(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT, {})
    r = LiquidationDetector().detect(snap, dcfg)
    assert r.direction == "neutral"
    assert r.warnings


def test_onchain_exchange_netflow_out_is_bullish(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT,
                 {"exchange_netflow": {"netflow_total": -600.0, "status": "fresh"}})
    r = OnchainDetector().detect(snap, dcfg)
    assert r.direction == "bullish"
    assert "exchange_netflow_out" in r.events


def test_onchain_exchange_netflow_in_is_bearish(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT,
                 {"exchange_netflow": {"netflow_total": 300.0, "status": "fresh"}})
    r = OnchainDetector().detect(snap, dcfg)
    assert r.direction == "bearish"
    assert "exchange_netflow_in" in r.events


def test_macro_event_window_sets_constraint_detail(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT,
                 {"macro": {"risk_state": "risk_off", "event_in_window": True,
                            "event_name": "CPI", "status": "fresh"}})
    r = MacroDetector().detect(snap, dcfg)
    assert r.direction == "bearish"
    assert r.details["no_macro_event"] is False
    assert "macro_event_window" in r.events


def test_macro_missing_source_defaults_no_event(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT, {})
    r = MacroDetector().detect(snap, dcfg)
    assert r.direction == "neutral"
    assert r.details["no_macro_event"] is True


def test_vol_regime_high_vol_classification(dcfg, make_klines):
    rows = [(100, 103, 97, 100 + (i % 2), 1000.0) for i in range(30)]
    snap = _snap(make_klines, rows, {})
    r = VolRegimeDetector().detect(snap, dcfg)
    assert r.direction == "neutral"
    assert "high_vol" in r.events


def test_vol_regime_insufficient(dcfg, make_klines):
    snap = _snap(make_klines, _FLAT[:5], {})
    r = VolRegimeDetector().detect(snap, dcfg)
    assert r.warnings
