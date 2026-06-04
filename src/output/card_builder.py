"""卡片渲染（规格见 specs/card_layout.md）。

阶段1：快报 / 观望卡 / 信号卡（=D15 降级标准卡，无 LLM 策略师段）。
所有价格来自 plan_builder（D3），卡片不生成任何数字。纯文本（Telegram 直接发）。
展示层时间按本地时区，存储仍 UTC（D8）。
"""
from __future__ import annotations

from common import clock

_DIR_EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪",
              "long": "🟢", "short": "🔴", "none": "⚪"}
_DIR_TEXT = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}
_RADAR_LABEL = {"structure": "结构", "volume": "量能", "adx": "ADX", "fib": "斐波",
                "macd": "MACD", "rsi": "RSI", "wyckoff": "威科夫",
                "liquidation": "清算", "oi_funding": "OI/费率", "basis": "基差"}


def _bar(n: int, width: int = 5) -> str:
    n = max(0, min(width, int(n)))
    return "█" * n + "░" * (width - n)


def _price(p) -> str:
    return f"{p:,.1f}" if p is not None else "—"


def _now_local(cfg) -> str:
    tz = cfg.get("display.timezone", "Asia/Shanghai")
    return clock.to_local(clock.now_ts(), tz).strftime("%m-%d %H:%M")


def _price_of(a, cfg) -> float | None:
    m = (a.snapshot.sources.get("mark") or {}).get("price")
    return m if m else a.snapshot.last_close(cfg.require("timeframes.primary"))


def _ttl(cfg) -> str:
    n = cfg.get("plan_builder.signal_ttl_klines", 4)
    tf = cfg.require("timeframes.primary")
    return f"{n} 根 {tf}"


def _radar_block(radar: dict) -> str:
    lines = []
    for mod, val in radar.items():
        label = _RADAR_LABEL.get(mod, mod)
        lines.append(f"  {label:<4} {_bar(val)} {val}")
    return "\n".join(lines)


def _data_warn(a) -> str:
    dq = a.snapshot.data_quality
    if not dq.get("is_complete", True):
        return "⚠️ 数据不完整，结论仅供参考"
    if dq.get("has_stale_source"):
        return "⚠️ 部分数据源过期"
    return ""


def build_signal_card(a, cfg) -> str:
    """信号卡（评分≥阈值）。阶段1无 LLM → 降级标准卡（D15）。"""
    f, p = a.fusion, a.plan
    price = _price_of(a, cfg)
    emoji = _DIR_EMOJI.get(f.direction, "⚪")
    hc = f.hard_constraints
    hc_str = "  ".join(("趋势✓" if hc.get("trend_aligned") else "趋势✗",
                        "量能✓" if hc.get("volume_confirmed") else "量能✗",
                        "ADX✓" if hc.get("adx_sufficient") else "ADX✗"))
    sl = p.source_levels
    lines = [
        f"{emoji} BTC {_DIR_TEXT.get(f.direction,'')}信号 · 评分 {f.score}/100",
        "━━━━━━━━━━━━━━━━━━━━",
        f"价格 ${_price(price)}",
        "⚠️ 纯检测器结论（无 LLM 综合解读）",
        "",
        "📊 信号雷达",
        _radar_block(f.radar),
        "",
        "🧭 交易计划  ※价格由 plan_builder 计算",
        f"  方向    {_DIR_TEXT.get(f.direction,'')}（{p.direction}）",
        f"  入场区  ${_price(p.entry_zone[0])} – ${_price(p.entry_zone[1])}  ({'/'.join(sl.get('entry',[]))})",
        f"  止损    ${_price(p.stop_loss)}  ({'/'.join(sl.get('stop',[]))})",
        f"  目标    ${_price(p.targets[0])} / ${_price(p.targets[1])}  ({'/'.join(sl.get('target',[]))})",
        f"  盈亏比  {p.risk_reward} : 1",
        f"  失效    {p.invalid_if}",
        "",
        f"✅ 硬约束  {hc_str}",
    ]
    if a.risk.warnings:
        lines += ["", "⚠️ 风险提示", *[f"  · {w}" for w in a.risk.warnings]]
    if a.risk.position_advice:
        lines.append(f"  · {a.risk.position_advice}")
    bg = _background_line(a)
    if bg:
        lines += ["", "🌐 背景", f"  {bg}"]
    w = _data_warn(a)
    if w:
        lines.append(w)
    lines += ["", f"⏰ 有效期 {_ttl(cfg)} · 发出 {_now_local(cfg)}",
              "   过期或刷新 → /btc --refresh"]
    return "\n".join(lines)


def build_wait_card(a, cfg) -> str:
    """观望卡（评分<阈值 / 被否决 / 无信号）—— 最常出现。"""
    f, p = a.fusion, a.plan
    price = _price_of(a, cfg)
    reasons = a.reasons or f.veto_reasons or ["综合评分不足"]
    kl = p.key_levels or {}
    res = kl.get("resistances", [])
    sup = kl.get("supports", [])
    lines = [
        f"⚪ BTC 观望 · 评分 {f.score}/100",
        "━━━━━━━━━━━━━━━━━━━━",
        f"价格 ${_price(price)}",
        "",
        "🤔 为什么不动",
        *[f"  · {r}" for r in reasons],
        "",
        "📍 关键位",
        "  上方阻力  " + (" / ".join(f"${_price(pp)} ({s})" for pp, s in res) or "—"),
        "  下方支撑  " + (" / ".join(f"${_price(pp)} ({s})" for pp, s in sup) or "—"),
    ]
    # 等什么
    lean = f.direction
    if lean == "bullish" and res:
        lines += ["", "⏳ 等什么", f"  站上 ${_price(res[0][0])} 且放量 → 看多确认"]
    elif lean == "bearish" and sup:
        lines += ["", "⏳ 等什么", f"  跌破 ${_price(sup[0][0])} 且放量 → 看空确认"]
    bg = _background_line(a)
    if bg:
        lines += ["", f"🌐 {bg}"]
    w = _data_warn(a)
    if w:
        lines.append(w)
    return "\n".join(lines)


def build_quick_card(a, cfg) -> str:
    """快报（/btc --quick，不调 LLM）。极简单行密排。"""
    f, p = a.fusion, a.plan
    price = _price_of(a, cfg)
    emoji = _DIR_EMOJI.get(f.direction, "⚪")
    kl = p.key_levels or {}
    res = " / ".join(f"${_price(pp)}" for pp, _ in kl.get("resistances", [])) or "—"
    sup = " / ".join(f"${_price(pp)}" for pp, _ in kl.get("supports", [])) or "—"
    lines = [
        f"⚡ BTC 快报 · 评分 {f.score}/100 {emoji}{_DIR_TEXT.get(f.direction,'')}",
        f"${_price(price)}",
        f"阻力 {res}  支撑 {sup}",
    ]
    if p.valid:
        lines.append(f"入场 ${_price(p.entry_zone[0])}-${_price(p.entry_zone[1])} "
                     f"止损 ${_price(p.stop_loss)} 目标 ${_price(p.targets[0])}/${_price(p.targets[1])}")
    lines.append(f"⏰{_ttl(cfg)}")
    return "\n".join(lines)


def _background_line(a) -> str:
    parts = []
    fr = (a.snapshot.sources.get("funding") or {}).get("rate")
    if fr is not None:
        parts.append(f"资金费率 {fr:+.4%}")
    oi = (a.snapshot.sources.get("oi") or {}).get("oi")
    if oi:
        parts.append(f"OI {oi:,.0f}")
    return " · ".join(parts)


def render(a, cfg, quick: bool = False) -> str:
    """按建议挑卡：quick → 快报；signal → 信号卡；否则观望卡。"""
    if quick:
        return build_quick_card(a, cfg)
    if a.recommendation == "signal" and a.plan.valid:
        return build_signal_card(a, cfg)
    return build_wait_card(a, cfg)
