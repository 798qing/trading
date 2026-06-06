"""llm.strategist — full-analysis prompt boundary and fallback."""
import textwrap
from types import SimpleNamespace

from common.config import load_config
from fusion.fusion import FusionResult
from llm.provider import LLMResponse
from llm.strategist import full_analysis
from plan.plan_builder import TradePlan
from review.risk import RiskResult


def _cfg(tmp_path):
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
        prompt_version: naked_chart_v1
        full_prompt_version: full_analysis_v1
        fail_pause_after: 1
        fail_pause_min: 30
        state_path: {str(state)!r}
        providers:
          deepseek:
            base_url: https://api.deepseek.com
            model: deepseek-chat
            api_key_secret: DEEPSEEK_API_KEY
    """
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return load_config(p, tmp_path / "missing.env")


def _analysis():
    snap = SimpleNamespace(
        symbol="BTC-USDT-SWAP",
        snapshot_id="snap1",
        analysis_ts=1_700_000_000,
        data_quality={"is_complete": True},
    )
    fusion = FusionResult(
        score=72,
        direction="bullish",
        recommendation="signal",
        vetoed=False,
        hard_constraints={"trend_aligned": True},
        radar={"structure": 4},
    )
    plan = TradePlan(
        "long", True, entry_zone=[99.0, 100.0], stop_loss=97.0,
        targets=[104.0, 107.0], invalid_if="15m 收盘跌破 97.0",
        risk_reward=1.8, source_levels={"entry": ["fib_ret"]},
        key_levels={"resistances": [[104.0, "swing_high"]], "supports": []},
    )
    return SimpleNamespace(
        snapshot=snap,
        fusion=fusion,
        plan=plan,
        risk=RiskResult(False, warnings=["目标空间有限"], position_advice="建议仓位减半"),
        recommendation="signal",
        reasons=[],
        signals={"structure": {"direction": "bullish", "strength": 80, "events": []}},
    )


class _FakeRouter:
    def __init__(self):
        self.messages = None

    def chat(self, messages, *, temperature, max_tokens):
        self.messages = messages
        return LLMResponse("fake", "model-x", "综合判断：跟随计划，谨慎看多。")


def test_full_analysis_uses_router_and_returns_ok(tmp_path):
    cfg = _cfg(tmp_path)
    router = _FakeRouter()
    out = full_analysis(_analysis(), cfg, router=router)

    assert out.status == "ok"
    assert out.prompt_version == "full_analysis_v1"
    assert out.provider == "fake"
    assert "谨慎看多" in out.text
    prompt = "\n".join(m.content for m in router.messages)
    assert "不生成任何新的入场价" in prompt
    assert "entry_zone" in prompt


def test_full_analysis_falls_back_without_key(tmp_path):
    cfg = _cfg(tmp_path)
    out = full_analysis(_analysis(), cfg)

    assert out.status == "fallback"
    assert out.prompt_version == "naked_chart_v1"
    assert "missing DEEPSEEK_API_KEY" in (out.error or "")
