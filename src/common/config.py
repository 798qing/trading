"""配置加载 + config_version 指纹（P0-4）+ 启动断言（P0-5）。

- config_version：对“进评分/决策相关”部分做 SHA-256 指纹，写入 snapshot/analyses，
  使任何评分阈值变更都可在回测中追溯（P0-4）。display / ops 两段不参与指纹
  （纯展示/运维，热加载安全）。
- 启动断言：conflict_score_cap < push_threshold 等不变式不满足时拒绝加载（P0-5），
  让“危险配置”在启动期就炸掉，而不是在产出信号时才出错。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# 不参与 config_version 指纹的顶层段（改它们不影响评分可追溯性）
_VERSION_EXCLUDE: frozenset[str] = frozenset({"display", "ops", "meta"})

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "btc_config.yaml"
_DEFAULT_SECRETS = _REPO_ROOT / "config" / "secrets.env"


class ConfigError(Exception):
    """配置非法（断言失败 / 缺字段 / 解析错误）。启动期抛出，拒绝加载。"""


@dataclass(frozen=True)
class Config:
    data: dict[str, Any]
    version: str                       # cfg_<12位指纹>
    path: Path
    secrets: dict[str, str] = field(default_factory=dict, repr=False)

    def get(self, dotted: str, default: Any = None) -> Any:
        """点号路径取值，如 cfg.get('scoring.push_threshold')。"""
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def require(self, dotted: str) -> Any:
        """同 get，但缺失即抛 ConfigError（用于必需项）。"""
        sentinel = object()
        val = self.get(dotted, sentinel)
        if val is sentinel:
            raise ConfigError(f"缺少必需配置项：{dotted}")
        return val

    def secret(self, key: str, default: str | None = None) -> str | None:
        return self.secrets.get(key, default)

    @property
    def root(self) -> Path:
        """repo 根目录（= config 文件的上两级），用于把相对路径锚定到固定位置。"""
        return self.path.resolve().parent.parent

    @property
    def db_path(self) -> Path:
        """ops.db_path 的绝对路径，与进程 cwd 无关（hermes 从任意目录调都正确）。"""
        raw = Path(self.get("ops.db_path", "data/trading.db"))
        return raw if raw.is_absolute() else self.root / raw

    @property
    def prompt_version(self) -> str:
        """LLM/Skill 版本；无 LLM 时仍记录 naked-chart 口径，便于回测分组。"""
        return str(self.get("ops.llm.prompt_version", "naked_chart_v1"))


def _canonical(data: dict[str, Any]) -> bytes:
    """确定性序列化：排序键、紧凑分隔符，保证同内容同指纹。"""
    filtered = {k: v for k, v in data.items() if k not in _VERSION_EXCLUDE}
    return json.dumps(filtered, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def fingerprint(data: dict[str, Any]) -> str:
    """对评分相关配置计算 config_version。"""
    digest = hashlib.sha256(_canonical(data)).hexdigest()[:12]
    return f"cfg_{digest}"


def _assert_invariants(data: dict[str, Any]) -> None:
    """启动断言（P0-5 及相关一致性检查）。任一不满足 → ConfigError。"""
    scoring = data.get("scoring", {})
    push = scoring.get("push_threshold")
    cap = scoring.get("conflict_score_cap")
    std = scoring.get("standard_card_score")

    for name, val in (("push_threshold", push), ("conflict_score_cap", cap),
                      ("standard_card_score", std)):
        if not isinstance(val, (int, float)):
            raise ConfigError(f"scoring.{name} 必须是数值，得到 {val!r}")

    # P0-5 核心断言：多周期冲突上限必须低于推送阈值，否则冲突时仍可能误推
    if not (cap < push):
        raise ConfigError(
            f"P0-5 断言失败：conflict_score_cap({cap}) 必须 < push_threshold({push})"
        )
    if not (std <= push):
        raise ConfigError(
            f"断言失败：standard_card_score({std}) 应 ≤ push_threshold({push})"
        )

    # plan_builder 数值边界自洽
    pb = data.get("plan_builder", {})
    if pb:
        smin, smax = pb.get("stop_min_pct"), pb.get("stop_max_pct")
        if smin is not None and smax is not None and not (0 < smin < smax):
            raise ConfigError(
                f"断言失败：需 0 < stop_min_pct({smin}) < stop_max_pct({smax})"
            )
        rr = pb.get("min_risk_reward")
        if rr is not None and rr <= 0:
            raise ConfigError(f"断言失败：min_risk_reward({rr}) 必须 > 0")

    adx_min = data.get("hard_constraints", {}).get("contextual_veto", {}).get("adx_min")
    if adx_min is not None and adx_min < 0:
        raise ConfigError(f"断言失败：adx_min({adx_min}) 不能为负")


def _parse_secrets(path: Path) -> dict[str, str]:
    """极简 .env 解析：KEY=VALUE，忽略空行与 # 注释。缺文件返回空 dict。"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def load_config(config_path: str | Path | None = None,
                secrets_path: str | Path | None = None) -> Config:
    """加载并校验配置。断言失败 / 解析错误均抛 ConfigError。"""
    cfg_path = Path(config_path) if config_path else _DEFAULT_CONFIG
    sec_path = Path(secrets_path) if secrets_path else _DEFAULT_SECRETS

    if not cfg_path.exists():
        raise ConfigError(f"配置文件不存在：{cfg_path}")

    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML 解析失败：{e}") from e

    if not isinstance(data, dict):
        raise ConfigError(f"配置根节点应为映射，得到 {type(data).__name__}")

    _assert_invariants(data)   # 先断言，不通过绝不返回 Config

    return Config(
        data=data,
        version=fingerprint(data),
        path=cfg_path,
        secrets=_parse_secrets(sec_path),
    )
