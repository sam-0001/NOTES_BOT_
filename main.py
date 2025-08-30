# main.py

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

# --- Custom MongoDB Persistence Class ---
class MongoPersistence(BasePersistence):
    def __init__(self, mongo_url: str, db_name: str = "telegram_bot_db"):
        super().__init__()
        self.client = MongoClient(mongo_url)
        self.db = self.client[db_name]
        self.user_data_collection = self.db["user_data"]
        self.chat_data_collection = self.db["chat_data"]
        self.bot_data_collection = self.db["bot_data"]
        self.access_logs_collection = self.db["access_logs"]
        self.authorized_emails_collection = self.db["authorized_emails"]

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
        self.bot_data_collection.update_one({"_id": "bot_data_singleton"}, {"$set": {"data": data}}, upsert=True)

    async def update_chat_data(self, chat_id: int, data):
        self.chat_data_collection.update_one({"_id": chat_id}, {"$set": {"data": data}}, upsert=True)

    async def update_user_data(self, user_id: int, data):
        self.user_data_collection.update_one({"_id": user_id}, {"$set": {"data": data}}, upsert=True)
        
    async def flush(self): pass
    async def drop_chat_data(self, chat_id: int): self.chat_data_collection.delete_one({"_id": chat_id})
    async def drop_user_data(self, user_id: int): self.user_data_collection.delete_one({"_id": user_id})
    async def get_callback_data(self): return None
    async def get_conversations(self, name: str): return {}
    async def refresh_bot_data(self, bot_data): await self.update_bot_data(bot_data)
    async def refresh_chat_data(self, chat_id: int, chat_data): await self.update_chat_data(chat_id, chat_data)
    async def refresh_user_data(self, user_id: int, user_data): await self.update_user_data(user_id, user_data)
    async def update_callback_data(self, data): pass
    async def update_conversation(self, name: str, key, new_state): pass

# --- Bot and Web Server Setup ---
MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise ValueError("MONGO_URL environment variable not set!")

persistence = MongoPersistence(mongo_url=MONGO_URL)
application = (
    Application.builder()
    .token(config.TELEGRAM_BOT_TOKEN)
    .persistence(persistence)
    .connect_timeout(30)
    .read_timeout(30)
    .build()
)
app = FastAPI(docs_url=None, redoc_url=None)

# --- Main Bot Logic & Webhooks ---
async def main_setup() -> None:
    """Initializes the bot and registers all handlers."""
    # --- Conversation Handlers ---
    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("start", h.start)],
        states={
            h.AWAIT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.receive_email)],
            config.ASK_YEAR: [MessageHandler(filters.Regex(r"^(1st|2nd|3rd|4th) Year$"), h.received_year)],
            config.ASK_BRANCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.received_branch)],
            config.ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.received_name)],
        },
        fallbacks=[CommandHandler("cancel", h.cancel_onboarding)],
        persistent=True, name="full_onboarding_conv"
    )
    stats_conv = ConversationHandler(
        entry_points=[CommandHandler("stats", h.stats_command)],
        states={
            h.CHOOSING_STAT: [CallbackQueryHandler(h.stats_callback_handler)],
            h.STATS_AWAITING_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.stats_receive_year)]
        },
        fallbacks=[CommandHandler("stats", h.stats_command)], persistent=False, name="stats_conv"
    )
    feedback_conv = ConversationHandler(
        entry_points=[CommandHandler("suggest", h.suggestion_start)],
        states={
            h.AWAIT_FEEDBACK_BUTTON: [CallbackQueryHandler(h.prompt_for_feedback, pattern="^leave_feedback$")],
            h.AWAIT_FEEDBACK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.receive_feedback)],
        },
        fallbacks=[CommandHandler("cancel", h.cancel_feedback)], persistent=False, name="feedback_conv"
    )
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", h.broadcast_start)],
        states={
            h.CHOOSING_BROADCAST_TARGET: [CallbackQueryHandler(h.broadcast_target_chosen)],
            h.AWAITING_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.broadcast_year_received)],
            h.AWAITING_BRANCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.broadcast_branch_received)],
            h.AWAITING_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, h.broadcast_message_received)],
        },
        fallbacks=[CommandHandler("cancel", h.cancel_broadcast)], persistent=False, name="broadcast_conv"
    )
    admin_file_conv = ConversationHandler(
        entry_points=[
            CommandHandler("getnotes", h.admin_get_files_start),
            CommandHandler("getassignments", h.admin_get_files_start)
        ],
        states={
            h.ADMIN_CHOOSE_YEAR: [CallbackQueryHandler(h.admin_year_chosen, pattern="^admin_year_")],
            h.ADMIN_CHOOSE_BRANCH: [CallbackQueryHandler(h.admin_branch_chosen, pattern="^admin_branch_")],
            h.ADMIN_CHOOSE_SUBJECT: [CallbackQueryHandler(h.admin_subject_chosen, pattern="^admin_subject_")],
        },
        fallbacks=[], persistent=False, name="admin_file_conv"
    )

    # --- Register All Handlers ---
    application.add_handler(setup_conv)
    application.add_handler(stats_conv)
    application.add_handler(feedback_conv)
    application.add_handler(broadcast_conv)
    application.add_handler(admin_file_conv) # <-- Register the new admin conversation
    
    application.add_handler(CommandHandler("help", h.help_command))
    application.add_handler(CommandHandler("reset", h.reset_command))
    application.add_handler(CommandHandler("myinfo", h.myinfo_command))
    application.add_handler(CommandHandler("leaderboard", h.leaderboard_command))
    application.add_handler(CommandHandler("notice", h.get_notice_command))
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
    try:
        update_data = await request.json()
        update = Update.de_json(data=update_data, bot=application.bot)
        await application.process_update(update)
    except Exception as e:
        config.logger.error(f"Error processing update: {e}")

@app.on_event("startup")
async def on_startup(): await main_setup()
@app.on_event("shutdown")
async def on_shutdown(): await application.stop()
