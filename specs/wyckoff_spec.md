# wyckoff_spec —— Wyckoff 候选观察检测器

## 目标

`src/detectors/wyckoff.py` 的公式化规格。第一版 Wyckoff 只输出候选事件，按 D4 不进主评分、不触发推送，只作为观望卡观察字段。

## 输入

- primary 周期已冻结、已收线 K 线，或调用方指定周期。
- swing 参数来自 `detectors.structure`。

K 线数量不足时，返回 insufficient。

## Swing 可见性

与 `structure_spec` 一致，调用 `find_swings`。所有候选事件只能基于已确认、可见的 swing。

## 候选事件

最后一根已收线为 `last`。

| 条件 | 事件 | phase_hypothesis | invalid_if |
| --- | --- | --- | --- |
| `last.low < last_visible_swing_low and last.close > last_visible_swing_low` | `spring_candidate` | `accumulation` | 下一根同周期收盘跌破该 swing low |
| 无 spring 且 `last.high > last_visible_swing_high and last.close < last_visible_swing_high` | `utad_candidate` | `distribution` | 下一根同周期收盘升破该 swing high |

若 spring 与 UTAD 条件同根同时满足，优先输出 spring，因为实现中先检查 low 侧，且 `not events` 后才检查 high 侧。

## 固定输出规则

第一版强制：

```text
direction = neutral
confidence = low
strength = 2 if events else 1
details.needs_confirmation = true
```

## 输出 details

- `phase_hypothesis`
- `needs_confirmation`
- `confirmation_tf`
- 命中 spring 时：`swing_low`, `invalid_if`
- 命中 UTAD 时：`swing_high`, `invalid_if`

## Fusion 与推送规则

- `direction=neutral`，fusion 不把 Wyckoff 纳入方向评分。
- 候选事件只能进入观察字段。
- 候选事件不得单独触发推送。
- 只有阶段 3 回测证明稳定后，确认事件才允许升级进评分；升级前必须更新本规格。

## 反例

- 盘中刺破但未收回，不得输出 spring/UTAD candidate。
- 未确认 swing 不得参与候选事件判断。
- `*_candidate` 不得转换成 bullish/bearish。
