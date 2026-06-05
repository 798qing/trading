# 接入 hermes（gateway 共存方案）

交易 Agent **不自己跑 Telegram bot**（会和 hermes gateway 抢同一个 token → 409 冲突）。
改为:hermes 是唯一 Telegram 出口,交易 Agent 当它的**引擎**。两条路:

## 1. 快卡（quick_commands exec，绕过 LLM，秒回）

已写入 `~/.hermes/config.yaml` 的 `quick_commands`:

| 命令 | 作用 | 路径 |
|:--|:--|:--|
| `/btc`  | 默认卡（观望/信号），读热库 ~60ms | `cli` |
| `/btcq` | 快报 | `cli --quick` |
| `/btcr` | 强制 live 刷新（~2s） | `cli --refresh` |

每个是 `type: exec`,跑:
```
PYTHONPATH=/Users/lin/trading-agent/src /Users/lin/trading-agent/.venv/bin/python -m cli [...]
```
exec 不传用户参数,故 quick/refresh 各设独立命令。环境变量被 hermes 自动脱敏,
CLI 热路径不需要任何 key(只读库),--refresh 用 OKX 公开接口(免 key)。

## 2. 自然语言解读（skill，走 agent loop + DeepSeek）

`~/.hermes/skills/trading/btc-analysis/SKILL.md`:用户问"BTC 怎么样"时,
hermes 跑 `cli --json` 拿结构化包,用自己的 DeepSeek 解读,严守边界
(价格只引用 JSON、不下单、仓位离散措辞)。这就是架构里的"LLM 策略师"(阶段3),
复用 hermes 已配的 DeepSeek,无需另造 LLM 层。

## 生效 / 验证

改 config 后需重启 gateway:
```
hermes gateway restart
hermes gateway status
tail -20 ~/.hermes/logs/gateway.log | grep -i telegram   # 看 telegram connected
```
然后在 Telegram 给 hermes 发 `/btc`,应秒回观望/信号卡。

## 数据新鲜度（让 /btc 秒回的前提）

装 precompute launchd（每 15m 采集落库,养热库）:
```
sed "s#__HOME__#$HOME#g" deploy/ai.trading-agent.precompute.plist \
  > ~/Library/LaunchAgents/ai.trading-agent.precompute.plist
launchctl load ~/Library/LaunchAgents/ai.trading-agent.precompute.plist
```
没装 precompute 时,`/btc` 首次或库空会自动回退 live(~2s),之后仍走库。

## 回滚

- quick_commands:`~/.hermes/config.yaml` 改回 `quick_commands: {}`(有备份 `config.yaml.bak-before-btc-*`)。
- skill:删 `~/.hermes/skills/trading/btc-analysis/`。
- 两者改完 `hermes gateway restart`。
