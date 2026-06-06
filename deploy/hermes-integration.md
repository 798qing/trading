# 接入 hermes（gateway 共存方案）

交易 Agent **不自己跑 Telegram bot**（会和 hermes gateway 抢同一个 token → 409 冲突）。
改为:hermes 是唯一 Telegram 出口,交易 Agent 当它的**引擎**。两条路:

## 1. 快卡（quick_commands exec）

已写入 `~/.hermes/config.yaml` 的 `quick_commands`:

| 命令 | 作用 | 路径 |
|:--|:--|:--|
| `/btc`  | 默认卡（观望/信号），带 full-analysis LLM；失败自动降级 | `cli --llm` |
| `/btcq` | 快报（绕过 LLM，秒回） | `cli --quick` |
| `/btcr` | 强制 live 刷新（~2s） | `cli --refresh` |
| `/btcl` | full-analysis LLM 综合解读（兼容别名） | `cli --llm` |
| `/btch` | 健康检查（热库/结算/推送） | `cli --health` |
| `/btchist` | 最近分析/结算流水 | `cli --history --limit 10` |
| `/btcs` | 7 日结算绩效统计 | `cli --stats --days 7` |
| `/btcw` | 30 日自动权重建议（只读） | `cli --auto-weight --days 30` |

每个是 `type: exec`,跑:
```
PYTHONPATH=/Users/lin/trading-agent/src /Users/lin/trading-agent/.venv/bin/python -m cli [...]
```
exec 不传用户参数,故 quick/refresh/llm 各设独立命令。环境变量被 hermes 自动脱敏,
`/btc`/`/btcl` 显式调用仓库内 provider router:DeepSeek 主 + OpenAI-compatible
备用抽象,全失败则 naked-chart。`/btcq` 保留不调 LLM 的秒回路径；--refresh 用 OKX
公开接口(免 key)。

## 2. 自然语言解读（skill，走 agent loop + DeepSeek）

`~/.hermes/skills/trading/btc-analysis/SKILL.md`:用户问"BTC 怎么样"时,
hermes 跑 `cli --json` 拿结构化包,用自己的 DeepSeek 解读,严守边界
(价格只引用 JSON、不下单、仓位离散措辞)。仓库内也提供 `cli --llm` 的同类
full-analysis 支线,用于 `/btc`、`/btcl` 和本地验证；`/btcq` 保持裸检测器秒回。

## 生效 / 验证

改 config 后需重启 gateway:
```
hermes gateway restart
hermes gateway status
tail -20 ~/.hermes/logs/gateway.log | grep -i telegram   # 看 telegram connected
```
然后在 Telegram 给 hermes 发 `/btc`,应返回带 `🧠 LLM 综合解读` 的观望/信号卡。

## 数据新鲜度（让 /btc 秒回的前提）

装 launchd 常驻任务（预采集 + 健康巡检 + 周报统计）:
```
deploy/install-launchd.sh
```
没装 precompute 时,`/btc`/`/btcq` 首次或库空会自动回退 live(~2s),之后仍走库。
如需配置热更新的长运行预采集，可手动运行 `PYTHONPATH=src .venv/bin/python -m precompute --watch`；
该模式按 `ops.precompute_interval_min` 周期执行，并在周期之间热重载 config/secrets。

安装后会有三个本地任务:

| Label | 频率 | 作用 | 日志 |
|:--|:--|:--|:--|
| `ai.trading-agent.precompute` | 每 15 分钟 | live 采集、冻结快照、结算到期信号 | `data/precompute.log` |
| `ai.trading-agent.health` | 每 5 分钟 | 只读健康检查 | `data/health.log` |
| `ai.trading-agent.stats` | 每周一 08:05 | 7 日绩效统计 | `data/stats.log` |

## 回滚

- quick_commands:`~/.hermes/config.yaml` 改回 `quick_commands: {}`(有备份 `config.yaml.bak-before-btc-*`)。
- skill:删 `~/.hermes/skills/trading/btc-analysis/`。
- 两者改完 `hermes gateway restart`。
