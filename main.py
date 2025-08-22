# main.py
# This version uses a custom TinyDB class for robust, persistent storage on Render.

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
    BasePersistence,  # <-- Import BasePersistence to create our own
)
from tinydb import TinyDB

# Local imports
import config
import handlers as h

# ==============================================================================
# SECTION 1: CUSTOM TinyDB PERSISTENCE CLASS
# ==============================================================================
class TinyDBPersistence(BasePersistence):
    """A custom persistence class that uses TinyDB for storage."""
    def __init__(self, filepath: str):
        super().__init__()
        self.db = TinyDB(filepath)
        self.user_data_table = self.db.table('user_data')
        self.chat_data_table = self.db.table('chat_data')
        self.bot_data_table = self.db.table('bot_data')
        self.on_flush = False

    def _get_data_from_table(self, table):
        """Helper to convert TinyDB table data to the format PTB expects."""
        return {int(entry['key']): entry['value'] for entry in table.all()}

    def _update_table_with_data(self, table, data):
        """Helper to write PTB data into a TinyDB table."""
        table.truncate()  # Clear the table before writing
        entries = [{'key': str(k), 'value': v} for k, v in data.items()]
        if entries:
            table.insert_multiple(entries)

    async def get_bot_data(self):
        entry = self.bot_data_table.get(doc_id=1)
        return entry.get('value', {}) if entry else {}

    async def get_chat_data(self):
        return self._get_data_from_table(self.chat_data_table)

    async def get_user_data(self):
        return self._get_data_from_table(self.user_data_table)

    async def update_bot_data(self, data):
        self.bot_data_table.upsert({'value': data}, doc_id=1)

    async def update_chat_data(self, data):
        self._update_table_with_data(self.chat_data_table, data)

    async def update_user_data(self, data):
        self._update_table_with_data(self.user_data_table, data)
        
    async def flush(self):
        # TinyDB writes data immediately, so flush doesn't need to do anything.
        pass

# ==============================================================================
# SECTION 2: BOT AND WEB SERVER SETUP
# ==============================================================================

# Use our new custom TinyDBPersistence class
persistence = TinyDBPersistence(filepath=config.PERSISTENCE_FILEPATH)

application = (
    Application.builder()
    .token(config.TELEGRAM_BOT_TOKEN)
    .persistence(persistence)
    .build()
)

app = FastAPI(docs_url=None, redoc_url=None)

# ==============================================================================
# SECTION 3: MAIN BOT LOGIC & WEBHOOKS
# ==============================================================================

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
        persistent=True,
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

@app.post("/webhook")
async def webhook(request: Request) -> None:
    """Handles incoming updates from Telegram."""
    try:
        update_data = await request.json()
        update = Update.de_json(data=update_data, bot=application.bot)
        await application.process_update(update)
    except Exception as e:
        config.logger.error(f"Error processing update: {e}")

@app.on_event("startup")
async def on_startup():
    """Runs the bot initialization when the server starts."""
    await main_setup()

@app.on_event("shutdown")
async def on_shutdown():
    """Stops the bot gracefully when the server shuts down."""
    await application.stop()
