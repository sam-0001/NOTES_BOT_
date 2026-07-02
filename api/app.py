"""
api/app.py
~~~~~~~~~~
FastAPI application factory with deterministic startup order.
"""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import misc_router, webhook_router
from db.client import close_db, init_db, set_loop
from config import logger

import bot.handlers  # noqa: F401


def _run_bot() -> None:
    """Bot polling loop with auto-restart on crash."""
    from bot.instance import bot

    logger.info("Telegram bot polling loop started.")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as exc:
            logger.error("Bot polling crashed: %s — restarting in 5s", exc)
            time.sleep(5)


@asynccontextmanager
async def lifespan(application: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    try:
        # 1. Capture the running event loop context
        set_loop(asyncio.get_running_loop())
        
        # 2. Complete DB connection & indexing before opening any network polling
        await init_db()
        
        # 3. Start bot polling only after dependencies are ready
        bot_thread = threading.Thread(target=_run_bot, daemon=True, name="telebot-polling")
        bot_thread.start()
        
    except Exception as err:
        logger.critical("Fatal error during backend lifespan startup: %s", err, exc_info=True)
        raise err

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    await close_db()


def create_app() -> FastAPI:
    application = FastAPI(title="UNIEVAL Backend", lifespan=lifespan)
    application.include_router(webhook_router)
    application.include_router(misc_router)
    return application
