# volume_spec —— 量能检测器

## 目标

`src/detectors/volume.py` 的公式化规格。该检测器进入 fusion 评分，并为“突破缩量”结构性否决提供 `breakout_volume_ok`。

## 输入

- primary 周期已冻结、已收线 K 线。
- 参数来自 `detectors.volume`：
  - `spike_ratio`：暴量阈值，默认 2.0。
  - `breakout_min_ratio`：突破最低量能比，默认 1.2。

K 线数量 `< 21` 时，返回 insufficient：`direction=neutral, strength=1, confidence=low`。

## 计算

```text
avg_volume = SMA(volume[:-1], 20)
vol_ratio = last.volume / avg_volume
up_candle = last.close >= last.open
spike = vol_ratio >= spike_ratio
breakout_volume_ok = vol_ratio >= breakout_min_ratio
```

`avg_volume <= 0` 或无法计算时，返回 insufficient。

## 判定规则

| 条件 | 事件 | 方向 | strength | confidence |
| --- | --- | --- | --- | --- |
| `spike and up_candle` | `volume_spike` | bullish | `5 if vol_ratio >= spike_ratio * 1.5 else 4` | high |
| `spike and not up_candle` | `volume_spike` | bearish | `5 if vol_ratio >= spike_ratio * 1.5 else 4` | high |
| `not spike and vol_ratio >= 1.0` | 无 | neutral | 2 | medium |
| `not spike and vol_ratio < 1.0` | 无 | neutral | 1 | low |

## 输出 details

- `vol_ratio`：三位小数。
- `avg_volume`：四位小数。
- `spike`
- `up_candle`
- `breakout_volume_ok`
- `breakout_min_ratio`

## Fusion 使用

当 `structure.events` 包含 `breakout_up` 或 `breakdown`，且 `breakout_volume_ok=false` 时，fusion 触发 `structural_veto: 突破缩量`。

## 反例

- 量能本身无方向，只有在暴量时才结合当根阴阳线给方向。
- 均量计算不得包含最后一根，否则会稀释当前暴量。
- `breakout_volume_ok` 只表达量能是否够，不判断是否真的发生结构突破。
