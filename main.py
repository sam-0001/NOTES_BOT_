# main.py
# This version fixes the TypeError with an updated TinyDBPersistence class.

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
    BasePersistence,
)
from tinydb import TinyDB

# Local imports
import config
import handlers as h

# ==============================================================================
# SECTION 1: UPDATED TinyDB PERSISTENCE CLASS
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
        table.truncate()
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
        pass

    # --- ADDED METHODS TO COMPLY WITH NEWER PTB VERSIONS ---
    async def drop_chat_data(self, chat_id: int) -> None:
        self.chat_data_table.remove(doc_ids=[chat_id])

    async def drop_user_data(self, user_id: int) -> None:
        self.user_data_table.remove(doc_ids=[user_id])

    async def get_callback_data(self):
        # This feature is not used in this bot, returning None is safe.
        return None

    async def get_conversations(self, name: str):
        # This feature is not used in this bot, returning empty dict is safe.
        return {}

    async def refresh_bot_data(self, bot_data):
        self.bot_data_table.update({'value': bot_data}, doc_id=1)

    async def refresh_chat_data(self, chat_id: int, chat_data):
        self.chat_data_table.update({'value': chat_data}, doc_id=chat_id)

    async def refresh_user_data(self, user_id: int, user_data):
        self.user_data_table.update({'value': user_data}, doc_id=user_id)

    async def update_callback_data(self, data):
        # This feature is not used in this bot, so we can pass.
        pass

    async def update_conversation(self, name: str, key, new_state):
        # This feature is not used in this bot, so we can pass.
        pass

# ==============================================================================
# SECTION 2: BOT AND WEB SERVER SETUP (Unchanged)
# ==============================================================================

persistence = TinyDBPersistence(filepath=config.PERSISTENCE_FILEPATH)

application = (
    Application.builder()
    .token(config.TELEGRAM_BOT_TOKEN)
    .persistence(persistence)
    .build()
)

app = FastAPI(docs_url=None, redoc_url=None)

# ==============================================================================
# SECTION 3: MAIN BOT LOGIC & WEBHOOKS (Unchanged)
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

    await application.initialize()
    await application.start()

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
    await main_setup()

@app.on_event("shutdown")
async def on_shutdown():
    await application.stop()
