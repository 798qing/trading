"""llm.provider — OpenAI-compatible provider router and fail-pause gate."""
import json
import textwrap

import httpx
import pytest

from common.config import load_config
from llm.provider import ChatMessage, LLMRequestError, ProviderRouter


def _cfg(tmp_path, *, secrets: str = "", backup: str = "", fail_pause_after: int = 3):
    state = tmp_path / "llm_state.json"
    body = f"""
    meta: {{label: t, symbol: BTC-USDT-SWAP}}
    timeframes: {{all: ["15m"], primary: "15m", higher: [], min_klines: 300}}
    scoring: {{push_threshold: 65, standard_card_score: 60, conflict_score_cap: 55}}
    plan_builder: {{entry_max_deviation_pct: 2.0, stop_min_pct: 0.5, stop_max_pct: 5.0,
                   min_risk_reward: 1.5, atr_period: 14, signal_ttl_klines: 4}}
    hard_constraints: {{contextual_veto: {{adx_min: 18}}}}
    fusion:
      base_weights: {{structure: 1.5}}
      trend_multiplier: {{with_trend: 1.5, against_trend: 0.5}}
      data_quality_multiplier: {{exact: 1.0, approximated: 0.7, stale: 0.3, unavailable: 0.0}}
    ops:
      db_path: data/t.db
      llm:
        provider: deepseek
        backup_provider: {backup!r}
        timeout_sec: 5
        fail_pause_after: {fail_pause_after}
        fail_pause_min: 30
        state_path: {str(state)!r}
        providers:
          deepseek:
            base_url: https://api.deepseek.com
            model: deepseek-chat
            api_key_secret: DEEPSEEK_API_KEY
          qwen:
            base_url: https://dashscope.aliyuncs.com/compatible-mode
            model: qwen-plus
            api_key_secret: QWEN_API_KEY
    """
    cfg_path = tmp_path / "c.yaml"
    secrets_path = tmp_path / "secrets.env"
    cfg_path.write_text(textwrap.dedent(body), encoding="utf-8")
    secrets_path.write_text(textwrap.dedent(secrets), encoding="utf-8")
    return load_config(cfg_path, secrets_path), state


def test_router_uses_backup_when_primary_is_missing_key(tmp_path):
    cfg, _state = _cfg(tmp_path, secrets="QWEN_API_KEY=backup-key\n", backup="qwen")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "dashscope.aliyuncs.com"
        assert request.headers["Authorization"] == "Bearer backup-key"
        body = {
            "model": "qwen-plus",
            "choices": [{"message": {"content": "备用 provider 成功"}}],
            "usage": {"total_tokens": 12},
        }
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    resp = ProviderRouter(cfg, client=client, now=1_700_000_000).chat([
        ChatMessage("user", "hello")
    ])

    assert resp.provider == "qwen"
    assert resp.model == "qwen-plus"
    assert resp.content == "备用 provider 成功"


def test_router_records_pause_after_repeated_failures(tmp_path):
    cfg, state = _cfg(tmp_path, fail_pause_after=2)
    router = ProviderRouter(cfg, now=1_700_000_000)

    with pytest.raises(LLMRequestError):
        router.chat([ChatMessage("user", "hello")])
    with pytest.raises(LLMRequestError):
        router.chat([ChatMessage("user", "hello")])

    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["fail_count"] == 2
    assert saved["pause_until_ts"] == 1_700_000_000 + 30 * 60

    with pytest.raises(LLMRequestError, match="paused"):
        ProviderRouter(cfg, now=1_700_000_001).chat([ChatMessage("user", "hello")])
