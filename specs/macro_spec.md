# macro detector spec

阶段 3 因子。Consumes optional macro linkage/event data from `snapshot.sources.macro`.
The current repo has no macro collector yet; missing data must default to no event window.

## Input

- `snapshot.sources.macro.risk_state`: `risk_on`, `risk_off`, or `neutral`
- `snapshot.sources.macro.btc_nasdaq_corr`
- `snapshot.sources.macro.btc_dxy_corr`
- `snapshot.sources.macro.event_in_window`
- `snapshot.sources.macro.event_name`
- config: `hard_constraints.contextual_veto.macro_event_window_min`

## Formula

- missing macro source: neutral, `details.no_macro_event=true`
- `risk_state=risk_on`: bullish, event `risk_on`
- `risk_state=risk_off`: bearish, event `risk_off`
- `event_in_window=true`: add event `macro_event_window`, set `details.no_macro_event=false`

Fusion must read `details.no_macro_event`. If false, the signal is contextually vetoed.

## Missing Data

Missing macro data is not a data-quality failure. It returns neutral and assumes no active macro event window.
