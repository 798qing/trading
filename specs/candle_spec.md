# candle_spec —— K 线形态检测器

## 目标

`src/detectors/candle.py` 的公式化规格。该检测器进入 fusion 评分，用于识别吞没、锤子、射击之星与十字星。

## 输入

- primary 周期已冻结、已收线 K 线，或调用方指定周期。
- 至少 3 根 K 线。

K 线数量 `< 3` 时，返回 insufficient。最后一根 `high-low <= 0` 时，输出 `pattern=flat` 的 neutral 结果。

## 基础量

最后一根为 `c`，前一根为 `p`：

```text
rng = c.high - c.low
body = abs(c.close - c.open)
upper_wick = c.high - max(c.open, c.close)
lower_wick = min(c.open, c.close) - c.low
bull = c.close > c.open
bear = c.close < c.open
```

## 判定顺序

按以下顺序命中第一个形态：

| 条件 | pattern/event | direction | strength | needs_confirmation |
| --- | --- | --- | --- | --- |
| `bull and p.close < p.open and c.close >= p.open and c.open <= p.close` | `bullish_engulfing` | bullish | 4 | false |
| `bear and p.close > p.open and c.open >= p.close and c.close <= p.open` | `bearish_engulfing` | bearish | 4 | false |
| `lower_wick >= 2 * body and upper_wick <= body and body > 0` | `hammer` | bullish | 3 | true |
| `upper_wick >= 2 * body and lower_wick <= body and body > 0` | `shooting_star` | bearish | 3 | true |
| `body <= rng * 0.1` | `doji` | neutral | 2 | true |
| 其他 | `none` | neutral | 1 | false |

## Confidence

```text
high   if strength >= 4 and not needs_confirmation
medium if strength >= 3
low    otherwise
```

## 输出 details

- `pattern`
- `needs_confirmation`
- `body`
- `upper_wick`
- `lower_wick`

## 反例

- 锤子、射击之星、十字星需确认，不得当作高置信即时信号。
- 吞没判断只包裹前一根真实体，不要求包裹全 K 线高低。
- 形态位置未纳入本检测器，后续由结构/斐波/风控综合判断。
