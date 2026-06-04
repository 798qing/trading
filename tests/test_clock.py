"""clock.py — UTC 基准与防前视收线判定（D7/D8）。"""
from common import clock


def test_floor_ts_aligns_to_tf():
    # 15m = 900s；09:07:13 → 09:00:00
    ts = 1_780_000_033  # 任意
    f = clock.floor_ts(ts, "15m")
    assert f % 900 == 0
    assert f <= ts < f + 900


def test_last_closed_ts_excludes_forming_candle():
    # 现在处于某根 15m 之中，last_closed 必须是上一根，且已收线
    now = clock.floor_ts(1_780_000_000, "15m") + 130  # 当前根内 +130s
    lc = clock.last_closed_ts("15m", now=now)
    assert clock.is_closed(lc, "15m", now=now)            # 已收线
    assert not clock.is_closed(lc + 900, "15m", now=now)  # 下一根（当前根）未收线
    assert lc + 900 <= now < lc + 1800


def test_is_closed_boundary():
    open_ts = 1_780_000_000
    assert clock.is_closed(open_ts, "5m", now=open_ts + 300)      # 恰好收线
    assert not clock.is_closed(open_ts, "5m", now=open_ts + 299)  # 差 1s


def test_to_local_keeps_instant():
    ts = 1_780_000_000
    local = clock.to_local(ts, "Asia/Shanghai")
    assert int(local.timestamp()) == ts  # 时区转换不改变瞬时
