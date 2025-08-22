# main.py
# This version is optimized for hosting on Render with a persistent disk.

import asyncio
import os
import uvicorn
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    JSONPersistence,  # <-- 1. Import JSONPersistence
)

# Local imports
import config
import handlers as h

# --- Bot and Web Server Setup ---
# 2. Use JSONPersistence, saving to the path on the persistent disk
persistence = JSONPersistence(filepath=config.PERSISTENCE_FILEPATH)

application = (
    Application.builder()
    .token(config.TELEGRAM_BOT_TOKEN)
    .persistence(persistence)
    .build()
)

app = FastAPI(docs_url=None, redoc_url=None)

# --- Main Bot Logic ---
async def main_setup() -> None:
    """Initializes the bot and its handlers."""
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", h.start)],
        states={
            config.ASK_YEAR: [MessageHandler(filters.Regex(r"^(1st|2nd|3rd|4th) Year$"), h.received_year)],
            config.ASK_BRANCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.received_branch)],
            config.ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.received_name)],
        },
        fallbacks=[CommandHandler("start", h.start)],
        persistent=True,  # <-- 3. Set persistent back to True
        name="setup_conversation"
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", h.help_command))
    application.add_handler(CommandHandler("myinfo", h.myinfo_command))
    application.add_handler(CommandHandler("reset", h.reset_command))
    application.add_handler(CommandHandler("notes", h.file_selection_command))
    application.add_handler(CommandHandler("assignments", h.file_selection_command))
    application.add_handler(CallbackQueryHandler(h.button_handler))

    # Initialize the application
    await application.initialize()
    await application.start()

    # --- Webhook Logic for Render ---
    webhook_base_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("LOCAL_WEBHOOK_URL")

    if webhook_base_url:
        webhook_url = f"{webhook_base_url}/webhook"
        await application.bot.set_webhook(url=webhook_url)
        config.logger.info(f"Webhook set successfully to {webhook_url}")
    else:
        config.logger.warning("Webhook URL not found. Set RENDER_EXTERNAL_URL or LOCAL_WEBHOOK_URL.")

# --- Webhook Endpoint ---
@app.post("/webhook")
async def webhook(request: Request) -> None:
    """Handles incoming updates from Telegram."""
    try:
        update_data = await request.json()
        update = Update.de_json(data=update_data, bot=application.bot)
        await application.process_update(update)
    except Exception as e:
        config.logger.error(f"Error processing update: {e}")

# --- Server Lifecycle ---
@app.on_event("startup")
async def on_startup():
    """Runs the bot initialization when the server starts."""
    await main_setup()

@app.on_event("shutdown")
async def on_shutdown():
    """Stops the bot gracefully when the server shuts down."""
    await application.stop()
