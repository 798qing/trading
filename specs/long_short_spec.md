# long_short detector spec

阶段 3 因子。消费 CoinGlass account long/short ratio，识别“未到极端拥挤区间”的仓位倾斜，作为低权重情绪/仓位背景。

## Input

- `snapshot.sources.long_short.long_ratio`
- `snapshot.sources.long_short.short_ratio`
- `snapshot.sources.long_short.long_short_ratio`
- config:
  - `detectors.long_short.bullish_ratio`
  - `detectors.long_short.bearish_ratio`
  - `detectors.long_short.account_bias_ratio`
  - `detectors.long_short.extreme_long_ratio`
  - `detectors.long_short.extreme_short_ratio`
  - `detectors.long_short.extreme_account_ratio`

## Formula

First check extreme crowding:

- `long_extreme = long_short_ratio >= extreme_long_ratio OR long_ratio >= extreme_account_ratio`
- `short_extreme = long_short_ratio <= extreme_short_ratio OR short_ratio >= extreme_account_ratio`

If either extreme condition is true, return `direction=neutral`, events include `deferred_to_liquidation`. Extreme crowding is handled contrarian by `liquidation`, not double-counted here.

For non-extreme data:

- `long_bias = long_short_ratio >= bullish_ratio OR long_ratio >= account_bias_ratio`
- `short_bias = long_short_ratio <= bearish_ratio OR short_ratio >= account_bias_ratio`
- `long_bias` only: `direction=bullish`, event `long_bias`
- `short_bias` only: `direction=bearish`, event `short_bias`
- otherwise: `direction=neutral`, event `long_short_balanced`

## Missing Data

If `long_short` is unavailable, return neutral strength 1 with a warning. Do not block analysis.
