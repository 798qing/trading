# trading-agent

纯分析、不下单的交易分析 Agent。Telegram `/btc` 输出结构化分析卡片，首发 BTC-USDT-SWAP（OKX 永续）。

> 设计与决策见 Obsidian「BTC交易Agent-重建包」：`00-启动执行手册.md`（入口）、`架构设计.md`、两份评审、`specs/`。
> 施工以**启动执行手册**为准。

## 硬边界
- ❌ 不执行交易、不连下单 API、不托管资金。只做分析与建议。
- ❌ LLM 不生成任何价格（入场/止损/止盈）；价格只由 `plan_builder.py` 从结构/斐波/ATR 算出。
- ✅ 仓位建议只能是离散、保守措辞（如「建议仓位减半」）。

## 环境
- Python 3.11+（本机用 `~/.local/bin/python3.11`，venv 在 `.venv/`）
- SQLite（WAL 模式，单写入者）

## 快速开始
```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config/secrets.env.example config/secrets.env   # 填入真实 key（已 gitignore）
.venv/bin/python -m pytest                          # 跑测试
PYTHONPATH=src .venv/bin/python -m cli --push                      # 显式按阶段2规则主动推送
PYTHONPATH=src .venv/bin/python -m cli --llm                       # full-analysis LLM 解读（失败自动降级）
PYTHONPATH=src .venv/bin/python -m cli --health                    # 检查热库/结算/推送状态
PYTHONPATH=src .venv/bin/python -m cli --history --limit 10         # 查看最近分析/结算流水
PYTHONPATH=src .venv/bin/python -m cli --stats --days 7            # 查看已结算信号表现
PYTHONPATH=src .venv/bin/python -m cli --auto-weight --days 30     # 输出自动调权重建议（只读）
deploy/install-launchd.sh                                          # 安装预采集/巡检/周报 launchd
```

## 目录
```
config/      btc_config.yaml（阈值/权重，含 version）  secrets.env（gitignored）
specs/       每个检测器规格 + trade_lifecycle.md
src/
  common/    config.py(版本指纹+断言)  clock.py(UTC)  returns.py(对数收益率)
  data/      collectors/  snapshot.py  store.py(SQLite WAL)
  detectors/ base.py(schema+swing防前视)  structure/volume/adx/fib ...
  fusion/    fusion.py(硬约束+权重+weight_breakdown)
  plan/      plan_builder.py(价格唯一来源)
  review/    validate.py  risk.py
  llm/       provider.py(DeepSeek)  strategist.py  skills/
  output/    card_builder.py  push.py  push_service.py  telegram.py
  backtest/  settle.py  metrics.py  weighting.py
  ops/       health.py
tests/
bot.py / main.py
```

## 关键决策（摘要，全文见手册）
- D3 LLM 不生成价格 · D6 快照冻结 snapshot_id · D7 只用已收线 K 线
- D8 全链路 UTC，仅展示层转时区 · D9 SQLite WAL + 单写入者 · D10 对数收益率为统一底座
- D15 LLM：DeepSeek 主 + OpenAI-compatible 备用抽象 → naked-chart 兜底
- 部署：本地 launchd 常驻

## 常驻与巡检
- `ai.trading-agent.precompute`：每 15 分钟采集落库并结算到期信号，不主动推送。
- `ai.trading-agent.health`：每 5 分钟执行 `cli --health`，日志在 `data/health.log`。
- `ai.trading-agent.stats`：每周一 08:05 执行 `cli --stats --days 7`，日志在 `data/stats.log`。
- 可选长运行预采集：`PYTHONPATH=src .venv/bin/python -m precompute --watch`，按配置周期执行并热重载 config/secrets。
- Hermes quick commands：`/btc` 默认裸检测器卡、`/btcq` 快报、`/btcr` 强制刷新、`/btcl` LLM 综合解读、`/btch` 健康检查、`/btchist` 最近流水、`/btcs` 7日统计、`/btcw` 30日权重建议。
- Stage 3 auto-weight：`cli --auto-weight` 只输出建议；样本少于 30 条已结算信号时只告警不改权重。
- Stage 3 full-analysis：默认 `/btc`/`cli` 仍走快路径；显式 `--llm` 才调用 provider router，LLM 不可用时卡片保留纯检测器结论。
- Stage 3 因子增强：CoinGlass 多空比已拆成 `long_short`（温和仓位倾斜，低权重）与 `liquidation`（极端拥挤反向风险），避免同源数据重复放大。
