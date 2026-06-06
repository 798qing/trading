"""config.py — 版本指纹（P0-4）与启动断言（P0-5）。"""
import textwrap

import pytest

from common.config import ConfigError, fingerprint, load_config

_MINIMAL = """
meta: {label: t, symbol: BTC-USDT-SWAP}
scoring: {push_threshold: 65, standard_card_score: 60, conflict_score_cap: 55}
plan_builder: {stop_min_pct: 0.5, stop_max_pct: 5.0, min_risk_reward: 1.5}
hard_constraints: {contextual_veto: {adx_min: 18}}
display: {timezone: Asia/Shanghai}
ops: {db_path: data/trading.db}
"""


def _write(tmp_path, body: str):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_loads_real_config_and_has_version():
    cfg = load_config()  # 仓库内 config/btc_config.yaml
    assert cfg.version.startswith("cfg_")
    assert cfg.get("scoring.push_threshold") == 65
    assert cfg.require("meta.symbol") == "BTC-USDT-SWAP"


def test_p05_assertion_rejects_cap_ge_push(tmp_path):
    bad = _MINIMAL.replace("conflict_score_cap: 55", "conflict_score_cap: 70")
    with pytest.raises(ConfigError, match="P0-5"):
        load_config(_write(tmp_path, bad))


def test_standard_card_must_not_exceed_push(tmp_path):
    bad = _MINIMAL.replace("standard_card_score: 60", "standard_card_score: 99")
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, bad))


def test_stop_bounds_must_be_ordered(tmp_path):
    bad = _MINIMAL.replace("stop_min_pct: 0.5", "stop_min_pct: 9.0")
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, bad))


def test_backtest_sample_min_score_within_standard_card_score(tmp_path):
    body = _MINIMAL.replace(
        "min_risk_reward: 1.5",
        "min_risk_reward: 1.5, backtest_sample_min_score: 61",
    )
    with pytest.raises(ConfigError, match="backtest_sample_min_score"):
        load_config(_write(tmp_path, body))


def test_display_ops_excluded_from_fingerprint(tmp_path):
    cfg_a = load_config(_write(tmp_path, _MINIMAL))
    # 只改 display/ops，指纹应不变
    changed = _MINIMAL.replace("Asia/Shanghai", "UTC").replace(
        "data/trading.db", "data/other.db")
    cfg_b = load_config(_write(tmp_path, changed))
    assert cfg_a.version == cfg_b.version


def test_scoring_change_moves_fingerprint(tmp_path):
    cfg_a = load_config(_write(tmp_path, _MINIMAL))
    changed = _MINIMAL.replace("push_threshold: 65", "push_threshold: 66")
    cfg_b = load_config(_write(tmp_path, changed))
    assert cfg_a.version != cfg_b.version


def test_fingerprint_deterministic():
    d = {"scoring": {"a": 1, "b": 2}, "display": {"x": 1}}
    assert fingerprint(d) == fingerprint({"display": {"x": 9}, "scoring": {"b": 2, "a": 1}})
