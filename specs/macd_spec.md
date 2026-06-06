# macd_spec —— MACD 动量检测器

## 目标

`src/detectors/macd.py` 的公式化规格。该检测器进入 fusion 评分，用于识别金叉、死叉、柱状方向与零轴对齐。

## 输入

- primary 周期已冻结、已收线 K 线，或调用方指定周期。
- close 序列。

`common.ta.macd(closes)` 返回 `None` 时，返回 insufficient：`direction=neutral, strength=1, confidence=low`。

## 计算

调用 `common.ta.macd` 得到完整序列：

```text
dif, dea, hist
golden = dif[-2] <= dea[-2] and dif[-1] > dea[-1]
death  = dif[-2] >= dea[-2] and dif[-1] < dea[-1]
above_zero = dif[-1] > 0
```

## 判定规则

| 条件 | 事件 | direction | strength | confidence |
| --- | --- | --- | --- | --- |
| `golden` | `golden_cross` | bullish | 4 | high |
| `death` | `death_cross` | bearish | 4 | high |
| `not golden/death and hist[-1] > 0` | 无 | bullish | 2 | medium |
| `not golden/death and hist[-1] < 0` | 无 | bearish | 2 | medium |
| `hist[-1] == 0` | 无 | neutral | 1 | low |

零轴对齐增强：

```text
if golden and above_zero: strength = 5, add zero_axis_aligned
if death and not above_zero: strength = 5, add zero_axis_aligned
```

## 输出 details

- `dif`：四位小数。
- `dea`：四位小数。
- `hist`：四位小数。
- `above_zero`

## 反例

- 柱状为正只能给弱多，不等同金叉。
- 金叉在零轴下方不得添加 `zero_axis_aligned`。
- MACD 不做背离检测；后续若实现背离，必须另补规格和测试。
