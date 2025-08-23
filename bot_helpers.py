# bot_helpers.py

import asyncio
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
import config  # <-- Added this import for OWNER_IDS

def busy_lock(func):
    """Decorator to prevent a user from running commands concurrently."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if context.user_data.get('is_busy', False):
            await update.effective_message.reply_text("⏳ Please wait, I'm processing your previous request.")
            return
        context.user_data['is_busy'] = True
        try:
            return await func(update, context, *args, **kwargs)
        finally:
            context.user_data['is_busy'] = False
    return wrapped


def check_user_setup(user_data):
    """Checks if the user has completed the initial setup."""
    return all(
        isinstance(user_data.get(key), str) and user_data.get(key).strip()
        for key in ['year', 'branch', 'name']
    )


async def send_wait_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Sends a waiting message if a task takes too long."""
    try:
        # Wait for 3 seconds before sending the message
        await asyncio.sleep(3)
        wait_message = (
            "We're getting your file, please wait. Thank you for your patience, "
            "we are always trying to make it faster! 🚀"
        )
        await context.bot.send_message(chat_id, wait_message)
    except asyncio.CancelledError:
        # This is expected if the download finishes in under 3 seconds
        pass

# --- ADDED THIS FUNCTION ---
def owner_only(func):
    """Decorator to restrict a command to owners only."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in config.OWNER_IDS:
            await update.message.reply_text("⛔ Sorry, you don't have permission to use this command.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped
