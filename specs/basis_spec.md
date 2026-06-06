# basis_spec —— 期现基差检测器

## 目标

`src/detectors/basis.py` 的公式化规格。该检测器进入 fusion 评分，用于表达永续标记价相对现货价的杠杆情绪。

## 输入

- `snapshot.sources.mark.price`：永续标记价。
- `snapshot.sources.spot.price`：现货最新成交价。

缺任一价格，或 `spot <= 0` 时，返回 insufficient：`direction=neutral, strength=1, confidence=low`。

## 计算

```text
basis_pct = (mark - spot) / spot * 100
```

## 判定规则

过热阈值：`HOT = 0.15`，单位为百分比。

| 条件 | 事件 | 方向 | strength | confidence | 含义 |
| --- | --- | --- | --- | --- | --- |
| `0 < basis_pct < 0.15` | `contango` | bullish | 3 | medium | 永续温和升水，多头需求占优 |
| `basis_pct >= 0.15` | `contango_hot` | bearish | 2 | low | 升水过热，杠杆多头拥挤，反偏空警惕 |
| `basis_pct < 0` | `backwardation` | bearish | 3 | medium | 永续贴水，避险/空头需求占优 |
| `basis_pct == 0` | 无 | neutral | 1 | low | 期现无明显偏离 |

## 输出 details

- `basis_pct`：四位小数。
- `mark`：输入标记价。
- `spot`：输入现货价。

## 反例

- 正基差不总是看多；超过过热阈值时必须转为低置信偏空警惕。
- 缺现货价不得用永续 last price 代替，否则会把合约内生价格误当期现基差。
- 基差检测器只读 snapshot，不自行实时拉取 OKX。
