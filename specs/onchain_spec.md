# onchain detector spec

阶段 3 因子。Consumes CryptoQuant BTC exchange netflow.

## Input

- `snapshot.sources.exchange_netflow.netflow_total`
- optional: `inflow_total`, `outflow_total`, `exchange`, `window`
- config:
  - `detectors.onchain.netflow_btc_threshold`
  - `detectors.onchain.netflow_btc_strong`

## Formula

- `abs_flow = abs(netflow_total)`
- if `abs_flow < netflow_btc_threshold`: neutral, event `netflow_muted`
- if `netflow_total > 0`: bearish, event `exchange_netflow_in`
- if `netflow_total < 0`: bullish, event `exchange_netflow_out`
- strength is 4 when `abs_flow >= netflow_btc_strong`, otherwise 3 for directional signals.

Rationale: exchange inflow is potential sell pressure; exchange outflow is supply leaving venues.

## Missing Data

If `exchange_netflow` is unavailable, return neutral strength 1 with a warning. Do not block analysis.
