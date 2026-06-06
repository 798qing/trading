# fib_spec —— 斐波那契位置检测器

## 目标

`src/detectors/fib.py` 的公式化规格。该检测器进入 fusion 雷达，用于表达当前价是否接近关键回撤/扩展位置，并把 levels 交给 plan_builder 作为 `source_levels` 候选。

## 输入

- primary 周期已冻结、已收线 K 线。
- swing 参数来自 `detectors.structure`。
- 斐波参数来自 `detectors.fib`：
  - `levels`：回撤比例，默认 `[0.382, 0.5, 0.618, 0.786]`。
  - `extensions`：扩展比例，默认 `[1.272, 1.618]`。
  - `confluence_tolerance_pct`：共振容差，默认 0.5%。

K 线数量不足、无可见 swing 高/低、或 swing 区间退化时，返回 insufficient。

## 计算

取最近可见 swing high 与 swing low：

```text
hi = swing_high.price
lo = swing_low.price
rng = hi - lo
up_leg = swing_high.idx > swing_low.idx
```

当 `up_leg=true`：

```text
ret_r = hi - rng * r
ext_r = hi + rng * (r - 1)
```

当 `up_leg=false`：

```text
ret_r = lo + rng * r
ext_r = lo - rng * (r - 1)
```

共振容差：

```text
tolerance = close * confluence_tolerance_pct / 100
at_key_level = min(abs(close - level_price)) <= tolerance
```

## 判定规则

| 条件 | 事件 | direction | strength | confidence |
| --- | --- | --- | --- | --- |
| `at_key_level=true` | `at_fib_level` | neutral | 4 | medium |
| `at_key_level=false` | 无 | neutral | 2 | low |

斐波位置不单独提供多空方向；方向由 structure、MACD、RSI 等检测器决定。

## 输出 details

- `swing_high`
- `swing_low`
- `up_leg`
- `levels`：回撤与扩展价格，两位小数。
- `nearest_level`
- `nearest_price`
- `at_key_level`
- `tolerance`

## 反例

- 不得用未确认 swing 计算斐波。
- 不得因为触及某个斐波位直接给 bullish/bearish。
- `hi <= lo` 的退化区间必须返回 insufficient。
