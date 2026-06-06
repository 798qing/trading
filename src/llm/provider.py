"""LLM provider abstraction with conservative fallback controls.

Providers use the OpenAI-compatible chat completions shape. The router tries
primary -> backup and returns a disabled/paused/error state to the caller so the
analysis path can fall back to naked-chart mode without blocking.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from common import clock


class LLMError(Exception):
    """Base LLM failure."""


class LLMConfigError(LLMError):
    """Provider is not configured enough to call."""


class LLMRequestError(LLMError):
    """Provider call failed or returned an invalid response."""


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMResponse:
    provider: str
    model: str
    content: str
    usage: dict[str, Any] | None = None


def _secret_name(provider: str) -> str:
    return f"{provider.upper()}_API_KEY"


def _base_url_secret(provider: str) -> str:
    return f"{provider.upper()}_BASE_URL"


def _model_secret(provider: str) -> str:
    return f"{provider.upper()}_MODEL"


def _provider_cfg(cfg, provider: str) -> dict:
    return cfg.get(f"ops.llm.providers.{provider}", {}) or {}


def _secret(cfg, key: str) -> str | None:
    return cfg.secret(key) or os.environ.get(key)


class OpenAICompatibleProvider:
    """Minimal chat-completions client for DeepSeek and compatible fallbacks."""

    def __init__(self, cfg, provider: str, *, client: httpx.Client | None = None):
        self.cfg = cfg
        self.provider = provider
        pcfg = _provider_cfg(cfg, provider)
        self.model = (
            _secret(cfg, _model_secret(provider))
            or pcfg.get("model")
            or ("deepseek-chat" if provider == "deepseek" else "chat")
        )
        self.base_url = (
            _secret(cfg, _base_url_secret(provider))
            or pcfg.get("base_url")
            or ("https://api.deepseek.com" if provider == "deepseek" else None)
        )
        self.api_key_name = pcfg.get("api_key_secret", _secret_name(provider))
        self.api_key = _secret(cfg, self.api_key_name)
        timeout = float(cfg.get("ops.llm.timeout_sec", 20))
        self._client = client or httpx.Client(timeout=timeout)

    def chat(self, messages: list[ChatMessage], *, temperature: float = 0.2,
             max_tokens: int = 900) -> LLMResponse:
        if not self.base_url:
            raise LLMConfigError(f"{self.provider}: missing base_url")
        if not self.api_key:
            raise LLMConfigError(f"{self.provider}: missing {self.api_key_name}")

        url = self.base_url.rstrip("/") + "/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [m.__dict__ for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = self._client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise LLMRequestError(f"{self.provider}: request failed: {e}") from e

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMRequestError(f"{self.provider}: invalid response shape") from e
        if not isinstance(content, str) or not content.strip():
            raise LLMRequestError(f"{self.provider}: empty response")
        return LLMResponse(
            provider=self.provider,
            model=str(body.get("model") or self.model),
            content=content.strip(),
            usage=body.get("usage") if isinstance(body.get("usage"), dict) else None,
        )


class ProviderRouter:
    """Try primary/backup providers and apply fail-pause gate across CLI runs."""

    def __init__(self, cfg, *, client: httpx.Client | None = None,
                 state_path: str | Path | None = None,
                 now: int | None = None):
        self.cfg = cfg
        self.client = client
        self.now = clock.now_ts() if now is None else now
        raw_state = state_path or cfg.get("ops.llm.state_path", "data/llm_state.json")
        p = Path(raw_state)
        self.state_path = p if p.is_absolute() else cfg.root / p

    def providers(self) -> list[str]:
        primary = str(self.cfg.get("ops.llm.provider", "deepseek") or "").strip()
        backup = str(self.cfg.get("ops.llm.backup_provider", "") or "").strip()
        names = [p for p in (primary, backup) if p]
        deduped: list[str] = []
        for name in names:
            if name not in deduped:
                deduped.append(name)
        return deduped

    def chat(self, messages: list[ChatMessage], *, temperature: float = 0.2,
             max_tokens: int = 900) -> LLMResponse:
        state = self._load_state()
        if self._paused(state):
            until = int(state.get("pause_until_ts") or 0)
            raise LLMRequestError(f"llm paused until {until}")

        errors: list[str] = []
        for provider in self.providers():
            try:
                resp = OpenAICompatibleProvider(
                    self.cfg, provider, client=self.client
                ).chat(messages, temperature=temperature, max_tokens=max_tokens)
            except LLMError as e:
                errors.append(str(e))
                continue
            self._save_state({"fail_count": 0, "pause_until_ts": 0, "last_error": ""})
            return resp

        self._record_failure("; ".join(errors) or "no provider configured")
        raise LLMRequestError("; ".join(errors) or "no provider configured")

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            body = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return body if isinstance(body, dict) else {}

    def _save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _paused(self, state: dict) -> bool:
        return int(state.get("pause_until_ts") or 0) > self.now

    def _record_failure(self, err: str) -> None:
        state = self._load_state()
        fail_count = int(state.get("fail_count") or 0) + 1
        pause_after = int(self.cfg.get("ops.llm.fail_pause_after", 3))
        pause_min = int(self.cfg.get("ops.llm.fail_pause_min", 30))
        pause_until = int(state.get("pause_until_ts") or 0)
        if fail_count >= pause_after:
            pause_until = self.now + pause_min * 60
        self._save_state({
            "fail_count": fail_count,
            "pause_until_ts": pause_until,
            "last_error": err,
            "last_failure_ts": self.now,
        })
