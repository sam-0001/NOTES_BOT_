# handlers.py

import io
import random
import asyncio
import pandas as pd
from datetime import datetime
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

# Local imports
import config
from drive_utils import get_drive_service, get_folder_id, list_items, download_file
from bot_helpers import owner_only, busy_lock, check_user_setup, send_wait_message, rate_limit

# Conversation states
CHOOSING_STAT = 0
AWAIT_FEEDBACK_BUTTON, AWAIT_FEEDBACK_TEXT = range(2)

# --- Conversation Handlers (/start) ---
# ... (The entire /start conversation: start, received_year, received_branch, received_name remains unchanged) ...

# --- Standard Command Handlers ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (code is unchanged)
    
async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (code is unchanged)

async def myinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (code is unchanged)
    
# --- Suggestion Conversation Handler ---

async def suggestion_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (code is unchanged)

async def prompt_for_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (code is unchanged)

async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (code is unchanged)
    
async def cancel_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (code is unchanged)

# --- Core Bot Functionality ---

@rate_limit(limit_seconds=10, max_calls=2) # Limit to 2 calls every 10 seconds
@busy_lock
async def file_selection_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /notes and /assignments with error recovery."""
    try:
        if not check_user_setup(context.user_data):
            await update.message.reply_text("Please run /start first to set up your profile.")
            return
        # ... (rest of the file selection logic is unchanged)
    except Exception as e:
        config.logger.error(f"Error in file_selection_command: {e}")
        await update.message.reply_text("❗️ An error occurred while communicating with Google Drive. Please try again later.")

@rate_limit(limit_seconds=5, max_calls=1) # Limit to 1 call every 5 seconds
async def get_notice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches notice with error recovery."""
    try:
        await update.message.reply_text("Checking for the latest notice, please wait...")
        # ... (rest of the notice logic is unchanged)
    except Exception as e:
        config.logger.error(f"Error in get_notice_command: {e}")
        await update.message.reply_text("❗️ Drive is temporarily unavailable for notices. Please try again later.")

# --- NEW Leaderboard Command ---
@rate_limit(limit_seconds=10, max_calls=1)
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the top 10 users with the most points."""
    await update.message.reply_text("🏆 Fetching the leaderboard...")
    db = context.application.persistence.db
    pipeline = [
        {"$match": {"data.points": {"$exists": True}}},
        {"$sort": {"data.points": -1}},
        {"$limit": 10}
    ]
    top_users = list(db["user_data"].aggregate(pipeline))
    if not top_users:
        await update.message.reply_text("The leaderboard is empty. Start downloading files to get points!")
        return
    leaderboard_text = "🏆 *Top 10 Study Champions*\n\n"
    rank_emojis = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    for i, user_doc in enumerate(top_users):
        user_data = user_doc.get("data", {})
        name = user_data.get("name", "A User")
        points = user_data.get("points", 0)
        leaderboard_text += f"{rank_emojis[i]} *{name}* - {points} points\n"
    await update.message.reply_text(leaderboard_text, parse_mode="Markdown")

# --- Admin Stats Command ---
@owner_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (code is unchanged)

async def stats_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (code is unchanged)

# --- UPDATED Callback Query Handler ---
@busy_lock
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles all inline button presses."""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("stats_"):
        return
        
    data_parts = query.data.split(":", 3)
    action = data_parts[0]
    
    if action == 'dl':
        # Award one point for downloading a file
        context.application.persistence.db["user_data"].update_one(
            {"_id": query.from_user.id},
            {"$inc": {"data.points": 1}},
            upsert=True
        )
        
        # ... (rest of the download logic with the wait message)
        
    # ... (rest of the button handler logic for 'subj' etc.)
