"""config_watcher.py — 配置热重载。"""
import os
import textwrap

from common.config_watcher import ConfigWatcher

_MINIMAL = """
meta: {label: t, symbol: BTC-USDT-SWAP}
scoring: {push_threshold: 65, standard_card_score: 60, conflict_score_cap: 55}
plan_builder: {stop_min_pct: 0.5, stop_max_pct: 5.0, min_risk_reward: 1.5}
hard_constraints: {contextual_veto: {adx_min: 18}}
display: {timezone: Asia/Shanghai}
ops: {db_path: data/trading.db}
"""


def _write(path, body, *, tick):
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    ns = 1_800_000_000_000_000_000 + tick
    os.utime(path, ns=(ns, ns))


def test_config_watcher_loads_and_reports_no_change(tmp_path):
    cfg_path = tmp_path / "c.yaml"
    secrets_path = tmp_path / "secrets.env"
    _write(cfg_path, _MINIMAL, tick=1)
    _write(secrets_path, "DEEPSEEK_API_KEY=old\n", tick=1)

    watcher = ConfigWatcher(cfg_path, secrets_path)
    cfg = watcher.load_initial()
    result = watcher.poll()

    assert cfg.require("meta.symbol") == "BTC-USDT-SWAP"
    assert cfg.secret("DEEPSEEK_API_KEY") == "old"
    assert result.changed is False
    assert result.config.version == cfg.version


def test_config_watcher_reloads_changed_config(tmp_path):
    cfg_path = tmp_path / "c.yaml"
    secrets_path = tmp_path / "secrets.env"
    _write(cfg_path, _MINIMAL, tick=1)
    _write(secrets_path, "", tick=1)
    watcher = ConfigWatcher(cfg_path, secrets_path)
    old = watcher.load_initial()

    changed = _MINIMAL.replace("push_threshold: 65", "push_threshold: 66")
    _write(cfg_path, changed, tick=2)
    result = watcher.poll()

    assert result.changed is True
    assert result.error is None
    assert result.previous_version == old.version
    assert result.current_version != old.version
    assert result.config.get("scoring.push_threshold") == 66


def test_config_watcher_keeps_previous_config_on_invalid_reload(tmp_path):
    cfg_path = tmp_path / "c.yaml"
    secrets_path = tmp_path / "secrets.env"
    _write(cfg_path, _MINIMAL, tick=1)
    _write(secrets_path, "", tick=1)
    watcher = ConfigWatcher(cfg_path, secrets_path)
    old = watcher.load_initial()

    invalid = _MINIMAL.replace("conflict_score_cap: 55", "conflict_score_cap: 70")
    _write(cfg_path, invalid, tick=2)
    result = watcher.poll()

    assert result.changed is True
    assert result.error and "P0-5" in result.error
    assert result.config.version == old.version
    assert watcher.config.version == old.version


def test_config_watcher_reloads_changed_secrets(tmp_path):
    cfg_path = tmp_path / "c.yaml"
    secrets_path = tmp_path / "secrets.env"
    _write(cfg_path, _MINIMAL, tick=1)
    _write(secrets_path, "DEEPSEEK_API_KEY=old\n", tick=1)
    watcher = ConfigWatcher(cfg_path, secrets_path)
    old = watcher.load_initial()

    _write(secrets_path, "DEEPSEEK_API_KEY=new\n", tick=2)
    result = watcher.poll()

    assert result.changed is True
    assert result.current_version == old.version
    assert result.config.secret("DEEPSEEK_API_KEY") == "new"
