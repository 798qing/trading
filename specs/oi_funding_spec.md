# oi_funding_spec —— OI + 资金费率检测器

## 目标

`src/detectors/oi_funding.py` 的公式化规格。该检测器进入 fusion 评分，用于表达永续市场拥挤度与 price x OI 趋势确认。

## 输入

- primary 周期已冻结 K 线，至少 6 根才启用 price x OI 组合。
- `snapshot.sources.funding.rate`：OKX funding rate，按 8h 费率读取。
- `snapshot.sources.oi.change_pct`：当前 OI 相对上一份冻结快照的变化百分比。

缺 `funding.rate` 且缺 `oi.change_pct` 时，返回 insufficient：`direction=neutral, strength=1, confidence=low`。

## 资金费率规则

阈值：`abs(rate) >= 0.0005` 视为极端拥挤。

- `rate >= 0.0005`：多头拥挤，事件 `funding_crowded_long`，score `-1`。
- `rate <= -0.0005`：空头拥挤，事件 `funding_crowded_short`，score `+1`。
- 其他：不改变 score。

资金费率按反向拥挤度解释，不单独代表趋势延续。

## Price x OI 组合

价格变化：`price_change = close[-1] - close[-6]`。

| 价格 | OI | 事件 | score | 含义 |
| --- | --- | --- | --- | --- |
| 上涨 | 上升 | `price_up_oi_up` | `+2` | 新多进场，趋势确认 |
| 上涨 | 下降 | `price_up_oi_down` | `0` | 空头回补，虚涨/中性 |
| 下跌 | 上升 | `price_down_oi_up` | `-2` | 新空进场，跌势确认 |
| 下跌 | 下降 | `price_down_oi_down` | `0` | 多头平仓，跌势减弱/中性 |

`price_change == 0` 按非上涨处理。`oi_change_pct == 0` 按非上升处理。

## 输出映射

- `score > 0` → `direction=bullish`
- `score < 0` → `direction=bearish`
- `score == 0` → `direction=neutral`
- `strength = min(5, 1 + abs(score))`
- `confidence = high` 当 `abs(score) >= 2`
- `confidence = medium` 当 `abs(score) == 1`
- `confidence = low` 当 `score == 0`

## 反例

- 价格上涨但 OI 下降，不得判强多；这通常是空头回补，不是新多主动进场。
- 资金费率极正不得判多；这是拥挤反向信号。
- 没有 OI 环比时仍可使用 funding，但不得生成 price x OI 事件。
