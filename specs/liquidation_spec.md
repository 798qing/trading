# liquidation detector spec

阶段 3 因子。当前没有逐笔 liquidation collector，先使用 CoinGlass account long/short ratio 作为清算/杠杆拥挤代理。

## Input

- `snapshot.sources.long_short.long_ratio`
- `snapshot.sources.long_short.short_ratio`
- `snapshot.sources.long_short.long_short_ratio`
- config:
  - `detectors.liquidation.crowded_long_ratio`
  - `detectors.liquidation.crowded_short_ratio`
  - `detectors.liquidation.crowded_account_ratio`

## Formula

- `long_hot = long_short_ratio >= crowded_long_ratio OR long_ratio >= crowded_account_ratio`
- `short_hot = long_short_ratio <= crowded_short_ratio OR short_ratio >= crowded_account_ratio`
- `long_hot` only: `direction=bearish`, event `long_crowding`
- `short_hot` only: `direction=bullish`, event `short_crowding`
- otherwise: `direction=neutral`, event `crowding_balanced`

The signal is contrarian: one-sided crowding raises liquidation squeeze risk against the crowded side.

## Missing Data

If `long_short` is unavailable, return neutral strength 1 with a warning. Do not block analysis.
