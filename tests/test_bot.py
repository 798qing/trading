"""bot.py — Telegram direct entrypoint wiring."""
from types import SimpleNamespace

import bot


class _Cfg:
    def get(self, key, default=None):
        return default


class _OKX:
    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _patch_common(monkeypatch, calls):
    analysis = SimpleNamespace(llm_output=None)

    monkeypatch.setattr(bot, "OKXClient", _OKX)
    monkeypatch.setattr(bot, "analyze", lambda store, cfg, okx: analysis)
    monkeypatch.setattr(bot, "persist", lambda store, cfg, a: calls.append(("persist", a.llm_output)))
    monkeypatch.setattr(bot.cb, "render", lambda a, cfg, quick: f"quick={quick} llm={bool(a.llm_output)}")

    return analysis


def test_run_analysis_adds_llm_output_by_default(monkeypatch):
    calls = []
    analysis = _patch_common(monkeypatch, calls)

    def fake_full_analysis(a, cfg):
        calls.append(("llm", a is analysis))
        return SimpleNamespace(to_dict=lambda: {"status": "ok", "text": "综合解读"})

    monkeypatch.setattr(bot, "full_analysis", fake_full_analysis)

    card = bot._run_analysis({"cfg": _Cfg(), "store": object()}, quick=False)

    assert card == "quick=False llm=True"
    assert analysis.llm_output == {"status": "ok", "text": "综合解读"}
    assert calls == [("llm", True), ("persist", analysis.llm_output)]


def test_run_analysis_skips_llm_for_quick(monkeypatch):
    calls = []
    _patch_common(monkeypatch, calls)
    monkeypatch.setattr(bot, "full_analysis", lambda *_args: calls.append(("llm", True)))

    card = bot._run_analysis({"cfg": _Cfg(), "store": object()}, quick=True)

    assert card == "quick=True llm=False"
    assert calls == [("persist", None)]
