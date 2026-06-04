"""validate.py + risk.py — 数值校验、风控降级、最终决策（只降级不升级）。"""
from types import SimpleNamespace

from plan.plan_builder import TradePlan
from review.risk import decide, review_risk
from review.validate import validate_plan


def _snap(mark=100.0, funding=0.0, is_complete=True, stale=False):
    return SimpleNamespace(
        sources={"mark": {"price": mark}, "funding": {"rate": funding}},
        data_quality={"is_complete": is_complete, "has_stale_source": stale},
    )


def _long(entry=(99.0, 100.0), stop=97.0, targets=(104.0, 107.0), rr=1.8,
          key=None):
    return TradePlan("long", True, entry_zone=list(entry), stop_loss=stop,
                     targets=list(targets), invalid_if="x", risk_reward=rr,
                     key_levels=key or {"resistances": [], "supports": []})


def _short(entry=(100.0, 101.0), stop=103.0, targets=(97.0, 94.0), rr=1.8):
    return TradePlan("short", True, entry_zone=list(entry), stop_loss=stop,
                     targets=list(targets), invalid_if="x", risk_reward=rr,
                     key_levels={"resistances": [], "supports": []})


# ---------- validate ----------
def test_validate_passes_clean_long(dcfg):
    r = validate_plan(_long(), _snap(mark=100.0), dcfg)
    assert r.ok and not r.reasons


def test_validate_entry_deviation_fails(dcfg):
    r = validate_plan(_long(), _snap(mark=130.0), dcfg)   # 入场远离标记价
    assert not r.ok and any("偏离" in x for x in r.reasons)


def test_validate_low_rr_fails(dcfg):
    r = validate_plan(_long(targets=(100.5, 101.0), rr=0.4), _snap(), dcfg)
    assert not r.ok and any("盈亏比" in x for x in r.reasons)


def test_validate_direction_inconsistent_fails(dcfg):
    r = validate_plan(_long(stop=101.0), _snap(), dcfg)   # 多单止损在入场上方
    assert not r.ok


def test_validate_wait_plan_not_ok(dcfg):
    r = validate_plan(TradePlan("none", False), _snap(), dcfg)
    assert not r.ok


# ---------- risk ----------
def test_risk_negative_funding_short_downgrades(dcfg):
    r = review_risk(_short(), SimpleNamespace(), _snap(funding=-0.0003), dcfg)
    assert r.downgrade and any("负资金费率" in x for x in r.reasons)


def test_risk_stale_data_position_advice(dcfg):
    r = review_risk(_long(), SimpleNamespace(), _snap(stale=True), dcfg)
    assert r.position_advice and "减半" in r.position_advice


def test_risk_incomplete_data_advice(dcfg):
    r = review_risk(_long(), SimpleNamespace(), _snap(is_complete=False), dcfg)
    assert r.position_advice and ("观望" in r.position_advice or "减半" in r.position_advice)


def test_risk_near_resistance_warns_not_downgrade(dcfg):
    # 上方阻力 100.5 紧贴入场上沿 100，风险 99-97=2 → 阻力空间 0.5 < 2 → 提示
    plan = _long(key={"resistances": [[100.5, "swing_high"]], "supports": []})
    r = review_risk(plan, SimpleNamespace(), _snap(), dcfg)
    assert not r.downgrade and any("阻力" in w for w in r.warnings)


# ---------- decide（只降级不升级）----------
def test_decide_fusion_wait_stays_wait(dcfg):
    fusion = SimpleNamespace(recommendation="wait", veto_reasons=["ADX<18"])
    rec, reasons = decide(fusion, validate_plan(_long(), _snap(), dcfg),
                          review_risk(_long(), None, _snap(), dcfg))
    assert rec == "wait" and reasons == ["ADX<18"]


def test_decide_validation_fail_forces_wait(dcfg):
    fusion = SimpleNamespace(recommendation="signal", veto_reasons=[])
    bad = validate_plan(_long(targets=(100.5, 101.0), rr=0.4), _snap(), dcfg)
    rec, reasons = decide(fusion, bad, review_risk(_long(), None, _snap(), dcfg))
    assert rec == "wait" and reasons


def test_decide_all_clear_is_signal(dcfg):
    fusion = SimpleNamespace(recommendation="signal", veto_reasons=[])
    rec, reasons = decide(fusion, validate_plan(_long(), _snap(), dcfg),
                          review_risk(_long(), None, _snap(), dcfg))
    assert rec == "signal" and not reasons
