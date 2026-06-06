# rsi_spec —— RSI 超买超卖检测器

## 目标

`src/detectors/rsi.py` 的公式化规格。该检测器进入 fusion 评分，采用均值回归读法：超卖偏多、超买偏空。

## 输入

- primary 周期已冻结、已收线 K 线，或调用方指定周期。
- close 序列。
- 参数来自 `detectors.rsi`：
  - `period`：默认 14。
  - `overbought`：默认 70。
  - `oversold`：默认 30。

`common.ta.rsi(closes, period)` 返回 `None` 时，返回 insufficient：`direction=neutral, strength=1, confidence=low`。

## 判定规则

| 条件 | 事件 | direction | strength | confidence |
| --- | --- | --- | --- | --- |
| `rsi <= oversold` | `oversold` | bullish | 3 | medium |
| `rsi >= overbought` | `overbought` | bearish | 3 | medium |
| 其他 | 无 | neutral | 2 | low |

## 输出 details

- `rsi`：两位小数。
- `overbought`
- `oversold`

## Fusion 与风控说明

RSI 是低权重辅助因子。强趋势行情中 RSI 可能长期处于极值，是否降级由 `risk.py` 结合 ADX 处理；本检测器只负责输出阈值命中。

## 反例

- 超买不等于立刻做空，只是偏空警惕。
- 超卖不等于立刻做多，只是偏多警惕。
- RSI 未命中阈值时不得强行给方向。
