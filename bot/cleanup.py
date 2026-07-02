"""
bot/cleanup.py
~~~~~~~~~~~~~~~
Keeps chats tidy.

Intermediate "menu" and "status" messages (subject lists, "uploading…",
"sending files…", admin prompts) are sent through `send_tracked` so their
message_ids are remembered. Once a flow reaches its natural end — files
delivered, an admin action finished — call `sweep` to delete every tracked
message for that chat, leaving only the final confirmation and the actual
notes/files behind.

Telegram lets a bot delete its own messages at any time (no 48h limit), so
this is safe to do even a while after the message was sent.
"""

from __future__ import annotations

import telebot

from bot.state import pop_transient_ids, track_transient


def send_tracked(bot: telebot.TeleBot, chat_id: int, text: str, **kwargs):
    """Send a message and remember it as sweepable."""
    msg = bot.send_message(chat_id, text, **kwargs)
    track_transient(chat_id, msg.message_id)
    return msg


def sweep(bot: telebot.TeleBot, chat_id: int) -> None:
    """Delete every tracked transient message for this chat."""
    for mid in pop_transient_ids(chat_id):
        try:
            bot.delete_message(chat_id, mid)
        except Exception:
            # Message may already be gone or too old for the API's liking —
            # never let cleanup crash a real flow.
            pass
