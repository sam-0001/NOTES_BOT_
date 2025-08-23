# main.py
# This version uses a custom MongoPersistence class for robust, persistent storage.

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
from pymongo import MongoClient

# Local imports
import config
import handlers as h

# ==============================================================================
# SECTION 1: CUSTOM MONGODB PERSISTENCE CLASS
# ==============================================================================
class MongoPersistence(BasePersistence):
    """A custom persistence class that uses MongoDB Atlas for storage."""
    def __init__(self, mongo_url: str, db_name: str = "telegram_bot_db"):
        super().__init__()
        self.client = MongoClient(mongo_url)
        self.db = self.client[db_name]
        self.user_data_collection = self.db["user_data"]
        self.chat_data_collection = self.db["chat_data"]
        self.bot_data_collection = self.db["bot_data"]

    async def get_bot_data(self):
        doc = self.bot_data_collection.find_one({"_id": "bot_data_singleton"})
        return doc.get("data", {}) if doc else {}

    async def get_chat_data(self):
        all_docs = self.chat_data_collection.find({})
        return {doc["_id"]: doc.get("data", {}) for doc in all_docs}

    async def get_user_data(self):
        all_docs = self.user_data_collection.find({})
        return {doc["_id"]: doc.get("data", {}) for doc in all_docs}

    async def update_bot_data(self, data):
        self.bot_data_collection.update_one(
            {"_id": "bot_data_singleton"}, {"$set": {"data": data}}, upsert=True
        )

    async def update_chat_data(self, chat_id: int, data):
        self.chat_data_collection.update_one(
            {"_id": chat_id}, {"$set": {"data": data}}, upsert=True
        )

    async def update_user_data(self, user_id: int, data):
        self.user_data_collection.update_one(
            {"_id": user_id}, {"$set": {"data": data}}, upsert=True
        )
        
    async def flush(self):
        pass
    
    # Methods required by newer PTB versions
    async def drop_chat_data(self, chat_id: int): 
        self.chat_data_collection.delete_one({"_id": chat_id})
    
    async def drop_user_data(self, user_id: int): 
        self.user_data_collection.delete_one({"_id": user_id})

    async def get_callback_data(self): return None
    async def get_conversations(self, name: str): return {}
    async def refresh_bot_data(self, bot_data): await self.update_bot_data(bot_data)
    async def refresh_chat_data(self, chat_id: int, chat_data): await self.update_chat_data(chat_id, chat_data)
    async def refresh_user_data(self, user_id: int, user_data): await self.update_user_data(user_id, user_data)
    async def update_callback_data(self, data): pass
    async def update_conversation(self, name: str, key, new_state): pass

# ==============================================================================
# SECTION 2: BOT AND WEB SERVER SETUP
# ==============================================================================

# Get the MongoDB URL from environment variables
MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise ValueError("MONGO_URL environment variable not set!")

# Use our new custom MongoPersistence class
persistence = MongoPersistence(mongo_url=MONGO_URL)

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
    application.add_handler(CommandHandler("suggest", h.suggestion_command)) 
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
