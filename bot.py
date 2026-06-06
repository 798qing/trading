"""Telegram 入口：/btc → 出卡。

纯分析不下单（D1）。/btc 默认带 LLM 综合解读；/btc --quick 出快报。
只响应配置中的 TELEGRAM_CHAT_ID（单用户），其余消息忽略。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# 让 repo 根目下的 bot.py 能 import src/ 内模块
sys.path.insert(0, str(Path(__file__).parent / "src"))

from telegram import Update                                    # noqa: E402
from telegram.ext import (Application, CommandHandler,          # noqa: E402
                          ContextTypes)

from analyze import analyze, persist                            # noqa: E402
from common.config import load_config                           # noqa: E402
from data.collectors.okx import OKXClient, OKXError             # noqa: E402
from data.store import Store                                    # noqa: E402
from llm.strategist import full_analysis                         # noqa: E402
from output import card_builder as cb                           # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s | %(message)s")
log = logging.getLogger("bot")


def _run_analysis(app_state: dict, quick: bool, llm: bool = True) -> str:
    """同步跑一次分析并落库，返回渲染好的卡片文本。"""
    cfg, store = app_state["cfg"], app_state["store"]
    with OKXClient(timeout=cfg.get("ops.llm.timeout_sec", 20)) as okx:
        a = analyze(store, cfg, okx=okx)
    if llm and not quick:
        a.llm_output = full_analysis(a, cfg).to_dict()
    try:
        persist(store, cfg, a)
    except Exception:                       # 落库失败不应阻塞回卡
        log.exception("persist 失败（不阻塞回卡）")
    return cb.render(a, cfg, quick=quick)


async def btc_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = ctx.application.bot_data
    chat_id = str(update.effective_chat.id)
    allowed = state.get("chat_id")
    if allowed and chat_id != str(allowed):
        log.warning("忽略非授权 chat_id=%s", chat_id)
        return

    args = ctx.args or []
    quick = any(a in ("--quick", "-q") for a in args)
    llm = not any(a in ("--no-llm", "--naked") for a in args)
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        # 阻塞的网络/计算放线程池，避免卡住 event loop
        import asyncio
        card = await asyncio.to_thread(_run_analysis, state, quick, llm)
    except OKXError as e:
        card = f"⚠️ 数据源不可用，暂时无法分析\n{e}"
    except Exception as e:                  # noqa: BLE001
        log.exception("分析失败")
        card = f"⚠️ 分析出错：{e}"
    await update.message.reply_text(card)


def build_app(cfg, store) -> Application:
    token = cfg.secret("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("缺少 TELEGRAM_BOT_TOKEN（config/secrets.env）")
    app = Application.builder().token(token).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["store"] = store
    app.bot_data["chat_id"] = cfg.secret("TELEGRAM_CHAT_ID")
    app.add_handler(CommandHandler("btc", btc_cmd))
    return app


def main() -> None:
    cfg = load_config()
    store = Store(cfg.db_path)
    store.init_db()
    app = build_app(cfg, store)
    log.info("bot 启动，配置版本 %s，监听 /btc …", cfg.version)
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
