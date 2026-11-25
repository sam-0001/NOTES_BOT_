"""
services/storage.py
~~~~~~~~~~~~~~~~~~~
Helper utilities for managing files in Telegram storage group/channel.
Handles automatic fallback and resolution between basic group IDs (-...)
and supergroup/channel IDs (-100...).
"""

import logging
from typing import Any
import telebot
import config.settings as settings
from bot.instance import bot

logger = logging.getLogger("unieval")


def get_storage_candidates() -> list[int | str]:
    """Return ordered list of chat IDs to try for storage operations."""
    primary = settings.STORAGE_GROUP_ID
    candidates: list[int | str] = []

    if primary:
        candidates.append(primary)

    raw_str = str(primary).strip().strip('"').strip("'")
    if raw_str.startswith("-100") and len(raw_str) > 4:
        # Basic group format without "100" (e.g. -1003916619709 -> -3916619709)
        alt = "-" + raw_str[4:]
        val = int(alt) if alt.lstrip("-").isdigit() else alt
        if val not in candidates:
            candidates.append(val)
    elif raw_str.startswith("-") and not raw_str.startswith("-100") and len(raw_str) > 1:
        # Supergroup format with "-100" (e.g. -3916619709 -> -1003916619709)
        alt = "-100" + raw_str[1:]
        val = int(alt) if alt.lstrip("-").isdigit() else alt
        if val not in candidates:
            candidates.append(val)
    elif raw_str.isdigit():
        alt1 = int("-" + raw_str)
        alt2 = int("-100" + raw_str)
        if alt1 not in candidates:
            candidates.append(alt1)
        if alt2 not in candidates:
            candidates.append(alt2)

    return candidates


def copy_to_storage(from_chat_id: int, message_id: int) -> telebot.types.Message:
    """
    Copy a message from admin to the storage chat, testing candidate IDs if needed.
    """
    candidates = get_storage_candidates()
    last_exc = None

    for target_id in candidates:
        try:
            logger.info("Attempting copy_message to storage chat %r (from %s, msg %s)", target_id, from_chat_id, message_id)
            msg = bot.copy_message(
                chat_id=target_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )
            if target_id != settings.STORAGE_GROUP_ID:
                logger.warning(
                    "STORAGE_GROUP_ID was %r, but worked with fallback %r! Updating runtime STORAGE_GROUP_ID.",
                    settings.STORAGE_GROUP_ID, target_id
                )
                settings.STORAGE_GROUP_ID = target_id
            return msg
        except Exception as exc:
            last_exc = exc
            err_msg = str(exc).lower()
            logger.warning("Failed copy_to_storage with target_id %r: %s", target_id, exc)
            if "chat not found" not in err_msg:
                # If error is permission or something else specific, don't keep trying candidate formats
                raise exc

    if last_exc:
        raise last_exc
    raise RuntimeError("No storage chat candidates configured")


def copy_from_storage(to_chat_id: int, message_id: int) -> telebot.types.Message:
    """
    Copy a message from storage chat to user, testing candidate IDs if needed.
    """
    candidates = get_storage_candidates()
    last_exc = None

    for target_id in candidates:
        try:
            msg = bot.copy_message(
                chat_id=to_chat_id,
                from_chat_id=target_id,
                message_id=message_id,
            )
            if target_id != settings.STORAGE_GROUP_ID:
                logger.warning(
                    "STORAGE_GROUP_ID was %r, but worked with fallback %r! Updating runtime STORAGE_GROUP_ID.",
                    settings.STORAGE_GROUP_ID, target_id
                )
                settings.STORAGE_GROUP_ID = target_id
            return msg
        except Exception as exc:
            last_exc = exc
            err_msg = str(exc).lower()
            if "chat not found" not in err_msg:
                raise exc

    if last_exc:
        raise last_exc
    raise RuntimeError("No storage chat candidates configured")


def test_storage_connection() -> tuple[bool, dict[str, Any]]:
    """
    Test whether the bot can access and post into the configured storage group.
    """
    candidates = get_storage_candidates()
    last_err = ""

    for target_id in candidates:
        try:
            chat = bot.get_chat(target_id)
            # Try sending a small verification message and deleting it
            test_msg = bot.send_message(target_id, "🧪 UniEval Storage Verification: connection verified.")
            try:
                bot.delete_message(target_id, test_msg.message_id)
            except Exception:
                pass

            if target_id != settings.STORAGE_GROUP_ID:
                logger.warning(
                    "STORAGE_GROUP_ID was %r, but worked with fallback %r! Updating runtime STORAGE_GROUP_ID.",
                    settings.STORAGE_GROUP_ID, target_id
                )
                settings.STORAGE_GROUP_ID = target_id

            return True, {
                "id": target_id,
                "title": getattr(chat, "title", "Storage"),
                "type": getattr(chat, "type", "group"),
            }
        except Exception as exc:
            last_err = str(exc)
            logger.warning("test_storage_connection failed for %r: %s", target_id, exc)

    return False, {"error": last_err, "candidates": candidates}
