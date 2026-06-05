# trade_lifecycle —— 信号生命周期与 outcome 判定（P0-1）

回测/胜率的口径源头。没有这份定义，胜率数字是虚高的（架构十六节）。
结算 job（P0-2）按本文实现 `settle.py::judge_outcome`。

## 输入
- 一条进入推送的信号 = `analyses` 行里的 `plan`（plan_builder 输出，价格唯一来源 D3）。
- 该信号的 `analysis_ts`（= 快照 primary 周期最近已收线 ts）。
- 之后的 primary 周期**已收线** K 线（重放，D7：不看未收线）。

只结算 `plan.valid=true` 且 `direction∈{long,short}` 的信号。
`plan` 无效（观望）→ outcome=`no_trade`，不计入任何分母。

## 有效期
- 默认 `signal_ttl_klines` 根 primary K 线（config，默认 4 根 15m = 1h）。
- 重放窗口 = `analysis_ts` **之后**的前 N 根已收线 K 线（严格 ts > analysis_ts）。

## 判定算法（按时间顺序逐根扫描）

```
entered = False
for k in 窗口内逐根:
    if not entered:
        # 入场区间被触及（K 线区间与 [entry_lo, entry_hi] 相交）
        if k.low <= entry_hi and k.high >= entry_lo:
            entered = True            # 当根即可能同时触及 TP/SL，继续往下判
    if entered:
        long:  tp = k.high >= tp1 ;  sl = k.low  <= stop
        short: tp = k.low  <= tp1 ;  sl = k.high >= stop
        if tp and sl: → 最不利方向（= SL）→ outcome=wrong, exit=sl_hit, 结束
        elif sl:      → outcome=wrong, exit=sl_hit, 结束
        elif tp:      → outcome=correct, exit=tp_hit, 结束

# 扫描完仍未结束：
if not entered:           → outcome=expired, entry_hit=0, exit=expired   # 不计入胜负分母
else:                     → outcome=partial, entry_hit=1, exit=expired   # 在场到期未达 TP/SL
                            partial 的盈亏方向 = 末根 close vs 入场（扣成本后净值符号）
```

**同一根同时触及 SL/TP → 判 SL（最不利方向，架构十六节）。** 保守，避免胜率虚高。

## 成本（计入净盈亏，用于 partial 方向判定与后续 EV/MDD）
- 手续费：taker 0.05%（双边）——保守按 taker；maker 0.02% 待精细化。
- 滑点：0.05%（双边）。
- 资金费率：每 8h 计入，按持有期跨越的结算次数 × 当时费率。
- `pnl_net% = 方向 × (出场价−入场价)/入场价 − 双边手续费 − 双边滑点 − 资金费率×持有结算次数`
- 入场价取入场区中点 `entry_ref`；出场价：correct=tp1，wrong=stop，partial=末根 close。

## 写回字段（analyses 表）
- `outcome`：correct / wrong / partial / expired / no_trade
- `entry_hit`：0/1
- `exit_reason`：tp_hit / sl_hit / expired / no_signal
- `outcome_note`：`pnl_net=<x>%`（+ 备注）
- `settled_ts`：结算回填时间

## 胜负分母口径（给回测/自动降权 D13）
- 分母 = `outcome ∈ {correct, wrong, partial}`（即 entry_hit=1 的已了结信号）。
- `expired`（未成交）与 `no_trade`（观望）**不计入**胜负分母。
- `correct` 计胜；`wrong` 计负；`partial` 按 `pnl_net` 符号归入胜/负（净正=胜）。

## 结算时机（P0-2 job）
- 每根 15m 收线后扫描 `outcome IS NULL` 且有效期已过（`now ≥ analysis_ts + N×tf + 一根缓冲`）的信号。
- 用库内已收线 K 线重放判定，回填上述字段。**全自动，不靠人工。**
