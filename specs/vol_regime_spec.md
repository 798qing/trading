# vol_regime detector spec

阶段 3 背景因子。Classifies current volatility regime using ATR%.

## Input

- primary timeframe closed klines from snapshot
- config:
  - `detectors.vol_regime.atr_period`
  - `detectors.vol_regime.high_atr_pct`
  - `detectors.vol_regime.low_atr_pct`

## Formula

- `atr_pct = ATR(period) / last_close * 100`
- if `atr_pct >= high_atr_pct`: event `high_vol`, strength 5
- if `atr_pct <= low_atr_pct`: event `low_vol`, strength 2
- otherwise: event `normal_vol`, strength 3

Direction is always neutral. This detector is radar/background only and must not create a trade direction.

## Missing Data

If K lines are insufficient to compute ATR, return neutral strength 1 with a warning.
