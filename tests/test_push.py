"""push.py — 阶段2推送去重/冷却策略。"""
from types import SimpleNamespace

from data.store import Store
from output.push import NEW_SIGNAL_TAG, UPDATE_TAG, evaluate, record_push


class _Cfg:
    def __init__(self):
        self.data = {
            "ops.push.dedup_window_sec": 60,
            "ops.push.cooldown_min": 240,
            "scoring.score_update_delta": 15,
        }

    def get(self, dotted, default=None):
        return self.data.get(dotted, default)


def _analysis(score=72, recommendation="signal", direction="long", entry=(99.0, 101.0)):
    return SimpleNamespace(
        recommendation=recommendation,
        snapshot=SimpleNamespace(symbol="BTC-USDT-SWAP"),
        fusion=SimpleNamespace(score=score),
        plan=SimpleNamespace(valid=True, direction=direction, entry_zone=entry),
    )


def _store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.init_db()
    return s


def test_new_signal_is_pushable_and_recorded(tmp_path):
    s = _store(tmp_path)
    a = _analysis()

    d = evaluate(a, _Cfg(), s, now=1000)
    assert d.should_push is True
    assert d.tag == NEW_SIGNAL_TAG

    pid = record_push(s, a, d, now=1000)
    assert pid > 0
    assert s.latest_push_event(d.signature)["tag"] == NEW_SIGNAL_TAG
    s.close()


def test_same_signal_is_deduped_then_cooled_down(tmp_path):
    s = _store(tmp_path)
    cfg = _Cfg()
    a = _analysis(score=72)
    record_push(s, a, evaluate(a, cfg, s, now=1000), now=1000)

    assert evaluate(_analysis(score=90), cfg, s, now=1020).reason == "dedup_window"
    d = evaluate(_analysis(score=80), cfg, s, now=1200)
    assert d.should_push is False
    assert d.reason == "cooldown"
    s.close()


def test_score_delta_over_threshold_updates_inside_cooldown(tmp_path):
    s = _store(tmp_path)
    cfg = _Cfg()
    a = _analysis(score=72)
    record_push(s, a, evaluate(a, cfg, s, now=1000), now=1000)

    d = evaluate(_analysis(score=90), cfg, s, now=1200)
    assert d.should_push is True
    assert d.tag == UPDATE_TAG
    assert d.reason == "score_update"
    s.close()


def test_wait_card_never_pushes(tmp_path):
    s = _store(tmp_path)
    d = evaluate(_analysis(recommendation="wait"), _Cfg(), s, now=1000)
    assert d.should_push is False
    assert d.reason == "not_signal"
    s.close()
