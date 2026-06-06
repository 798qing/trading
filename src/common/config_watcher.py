"""配置热更新 watcher。

检测 config/secrets 文件变化，安全重载配置；新配置非法时保留旧配置。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from common.config import Config, ConfigError, load_config


@dataclass(frozen=True)
class ReloadResult:
    changed: bool
    config: Config
    previous_version: str
    current_version: str
    error: str | None = None


def _file_signature(path: Path) -> tuple[bool, int, int]:
    try:
        st = path.stat()
    except FileNotFoundError:
        return (False, 0, 0)
    return (True, st.st_mtime_ns, st.st_size)


class ConfigWatcher:
    """轮询式配置 watcher；适合 launchd/长运行循环，无额外依赖。"""

    def __init__(self, config_path: str | Path | None = None,
                 secrets_path: str | Path | None = None,
                 loader: Callable[
                     [str | Path | None, str | Path | None], Config
                 ] = load_config):
        self.config_path = Path(config_path) if config_path else None
        self.secrets_path = Path(secrets_path) if secrets_path else None
        self._loader = loader
        self._config: Config | None = None
        self._signature: tuple[
            tuple[bool, int, int], tuple[bool, int, int]
        ] | None = None

    @property
    def config(self) -> Config:
        if self._config is None:
            return self.load_initial()
        return self._config

    def load_initial(self) -> Config:
        cfg = self._loader(self.config_path, self.secrets_path)
        self._config = cfg
        self.config_path = cfg.path
        self._signature = self._current_signature()
        return cfg

    def poll(self) -> ReloadResult:
        if self._config is None:
            cfg = self.load_initial()
            return ReloadResult(False, cfg, cfg.version, cfg.version)

        previous = self._config
        signature = self._current_signature()
        if signature == self._signature:
            return ReloadResult(False, previous, previous.version, previous.version)

        self._signature = signature
        try:
            cfg = self._loader(self.config_path, self.secrets_path)
        except ConfigError as e:
            return ReloadResult(
                True, previous, previous.version, previous.version, error=str(e)
            )

        self._config = cfg
        self.config_path = cfg.path
        return ReloadResult(True, cfg, previous.version, cfg.version)

    def _current_signature(self) -> tuple[tuple[bool, int, int],
                                           tuple[bool, int, int]]:
        config_path = self.config_path if self.config_path else Path("config/btc_config.yaml")
        secrets_path = (
            self.secrets_path if self.secrets_path
            else config_path.parent / "secrets.env"
        )
        return (_file_signature(config_path), _file_signature(secrets_path))
