# bot_helpers.py

import asyncio
from functools import wraps
from time import time
from telegram import Update
from telegram.ext import ContextTypes
import config

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
        await asyncio.sleep(3)
        wait_message = (
            "We're getting your file, please wait. Thank you for your patience, "
            "we are always trying to make it faster! 🚀"
        )
        await context.bot.send_message(chat_id, wait_message)
    except asyncio.CancelledError:
        pass

def rate_limit(limit_seconds: int = 5, max_calls: int = 3):
    """Decorator to limit how often a user can use a command."""
    def decorator(func):
        @wraps(func)
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id
            now = time()
            timestamps = context.user_data.get('rate_limit_timestamps', {}).get(func.__name__, [])
            timestamps = [ts for ts in timestamps if now - ts < limit_seconds]
            if len(timestamps) >= max_calls:
                await update.effective_message.reply_text("You are sending requests too quickly. Please wait a moment.")
                return
            timestamps.append(now)
            if 'rate_limit_timestamps' not in context.user_data:
                context.user_data['rate_limit_timestamps'] = {}
            context.user_data['rate_limit_timestamps'][func.__name__] = timestamps
            return await func(update, context, *args, **kwargs)
        return wrapped
    return decorator

def owner_only(func):
    """Decorator to restrict a command and alert on unauthorized access."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user.id not in config.OWNER_IDS:
            alert_message = (
                f"⚠️ *Unauthorized Access Alert*\n\n"
                f"A non-admin user tried to use an admin command.\n\n"
                f"👤 *User:* {user.first_name} (@{user.username})\n"
                f"🆔 *ID:* `{user.id}`\n"
                f"📝 *Command:* `{update.message.text}`"
            )
            config.logger.warning(f"Unauthorized access attempt by user {user.id}")
            if config.FEEDBACK_GROUP_ID:
                await context.bot.send_message(
                    chat_id=config.FEEDBACK_GROUP_ID,
                    text=alert_message,
                    parse_mode="Markdown"
                )
            await update.message.reply_text("⛔ Sorry, this is an admin-only command.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped
