# adx_spec —— ADX 趋势强度检测器

## 目标

`src/detectors/adx.py` 的公式化规格。该检测器进入 fusion 雷达与硬约束，但不提供多空方向。

## 输入

- primary 周期已冻结、已收线 K 线。
- 参数：
  - `detectors.adx.period`：默认 14。
  - `detectors.adx.strong`：强趋势阈值，默认 30。
  - `hard_constraints.contextual_veto.adx_min`：最小趋势阈值，默认 18。

`common.ta.adx(klines, period)` 返回 `None` 时，返回 insufficient：`direction=neutral, strength=1, confidence=low`。

## 计算

调用 `common.ta.adx` 得到：

```text
adx_val, plus_di, minus_di
```

ADX 只衡量趋势强弱，不决定方向；`plus_di/minus_di` 仅作为 details 背景字段。

## 判定规则

| 条件 | classification | direction | strength | confidence |
| --- | --- | --- | --- | --- |
| `adx_val >= strong` | `strong` | neutral | 5 | high |
| `adx_min <= adx_val < strong` | `trending` | neutral | 3 | medium |
| `adx_val < adx_min` | `no_trend` | neutral | 1 | high |

## 输出 details

- `adx`：两位小数。
- `plus_di`：两位小数。
- `minus_di`：两位小数。
- `classification`
- `adx_min`
- `strong_threshold`

## Fusion 使用

`details.adx < hard_constraints.contextual_veto.adx_min` 时，fusion 触发情境性否决 `ADX<min`。第一版没有 Wyckoff 确认事件豁免，因为 Wyckoff 只输出候选观察事件。

## 反例

- ADX 高不等于看多，也不等于看空。
- DI 交叉不得在本检测器中转成方向信号。
- ADX 不足时不得删除结果；应输出 `no_trend` 供 fusion veto。
