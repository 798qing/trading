# structure_spec —— 结构检测器

## 目标

`src/detectors/structure.py` 的公式化规格。该检测器进入 fusion 评分，用于识别 HH/HL/LH/LL 结构状态与结构性突破。

## 输入

- primary 周期已冻结、已收线 K 线，默认 `timeframes.primary`。
- 参数来自 `detectors.structure`：
  - `swing_lookback`：分形 swing 两侧窗口。
  - `swing_confirm_delay`：swing 确认延迟，防前视。

K 线数量 `< 2 * swing_lookback + 5` 时，返回 insufficient：`direction=neutral, strength=1, confidence=low`。

## Swing 可见性

调用 `find_swings(klines, lookback, confirm_delay)`：

```text
lag = max(lookback, confirm_delay)
high swing: high[i] 严格大于左右各 lookback 根 high，且 i + lag <= last_index
low swing:  low[i]  严格小于左右各 lookback 根 low， 且 i + lag <= last_index
```

严格不等号用于避免横盘等高平台被误判为多个 swing。`i + lag > last_index` 的 swing 尚未确认，不可见。

## 结构判定

取最近两个可见 swing high 与最近两个可见 swing low：

```text
hh = last_high > prev_high
hl = last_low  > prev_low
lh = last_high < prev_high
ll = last_low  < prev_low
```

| 条件 | structure | 方向 | strength |
| --- | --- | --- | --- |
| `hh and hl` | `uptrend` | bullish | 4 |
| `lh and ll` | `downtrend` | bearish | 4 |
| 其他 | `range` | neutral | 2 |

若可见 swing high 或 low 不足 2 个，返回 `structure=indeterminate`，`direction=neutral, strength=2, confidence=low`。

## 突破判定

用最后一根已收线 close 与最近可见 swing 高低比较：

| 条件 | 事件 | 方向修正 |
| --- | --- | --- |
| `close > last_swing_high` | `breakout_up` | 若原方向非 bearish，则 `direction=bullish, strength>=4` |
| `close < last_swing_low` | `breakdown` | 若原方向非 bullish，则 `direction=bearish, strength>=4` |

突破是否缩量不在本检测器判定，由 `volume.details.breakout_volume_ok` 提供给 fusion 的 structural veto。

## 输出 details

- `structure`
- `last_swing_high`
- `last_swing_low`
- `close`
- `hh`, `hl`, `lh`, `ll`

`strength >= 4` 时 `confidence=high`，否则 `confidence=medium`。

## 反例

- 未确认的最新极值不得作为 swing 使用。
- 等高/等低平台不得批量标记 swing。
- 结构突破只看已收线 close，不看盘中刺破。
