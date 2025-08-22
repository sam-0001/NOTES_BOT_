# bot_helpers.py

import asyncio
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

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
        # Wait for 7 seconds before sending the message
        await asyncio.sleep(7)
        await context.bot.send_message(chat_id, "This is taking a moment, please wait...")
    except asyncio.CancelledError:
        # This is expected if the main task finishes before the wait time
        pass
