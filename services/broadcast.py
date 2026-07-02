"""
services/broadcast.py
~~~~~~~~~~~~~~~~~~~~~
Broadcasts newly uploaded files to all existing buyers of a subject.

Designed to run in a background daemon thread so it never blocks bot
or FastAPI handlers.
"""

from __future__ import annotations

import time

from config import STORAGE_GROUP_ID, logger
from db.queries import fetch_buyers, fetch_subject, fetch_user_orders
from utils.sections import get_sections, has_section_access, is_section_free, section_price


def broadcast_batch(
    subject_id: str,
    section_name: str,
    new_file_ids: list[str],
    section_idx: int | None = None,
    new_texts: list[str] | None = None,
) -> None:
    """
    Send a batch of new file_ids to every buyer of `subject_id`.

    Import `bot` lazily to avoid circular imports (bot → handlers → broadcast).
    """
    from bot.instance import bot  # local import to break circular dependency

    new_texts = new_texts or []
    total_new = len(new_file_ids) + len(new_texts)

    subject = fetch_subject(subject_id)
    if not subject:
        logger.warning("broadcast_batch: subject %s not found.", subject_id)
        return

    sections = get_sections(subject)
    section = sections[section_idx] if section_idx is not None and section_idx < len(sections) else None
    buyers = fetch_buyers(subject_id)
    if not buyers:
        logger.info("broadcast_batch: no buyers for subject %s.", subject_id)
        return

    seen: set[str] = set()
    for order in buyers:
        chat_cid = order["chat_id"]
        if chat_cid in seen:
            continue
        seen.add(chat_cid)

        try:
            user_orders = fetch_user_orders(chat_cid)
            can_receive_files = (
                section is None
                or section_idx is None
                or has_section_access(user_orders, subject_id, section_idx, subject, section)
            )

            if can_receive_files:
                bot.send_message(
                    int(chat_cid),
                    f"🔔 *New Material Added!*\n\n"
                    f"📚 Subject: *{subject['name']}*\n"
                    f"📂 Section: *{section_name}*\n"
                    f"📄 {total_new} new item{'s' if total_new != 1 else ''} added!\n\n"
                    f"Sending them now…",
                    parse_mode="Markdown",
                )
                for mid in new_file_ids:
                    bot.copy_message(
                        chat_id=int(chat_cid),
                        from_chat_id=STORAGE_GROUP_ID,
                        message_id=int(mid),
                    )
                    time.sleep(0.05)
                for note_text in new_texts:
                    bot.send_message(int(chat_cid), note_text)
                    time.sleep(0.05)
            elif section and not is_section_free(subject, section):
                from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

                price = section_price(subject, section)
                kb = InlineKeyboardMarkup(row_width=1)
                kb.add(InlineKeyboardButton(
                    f"💳 Unlock for ₹{price}",
                    callback_data=f"buy_section:{subject_id}:{section_idx}",
                ))
                bot.send_message(
                    int(chat_cid),
                    f"🔔 *New Paid Material Added!*\n\n"
                    f"📚 Subject: *{subject['name']}*\n"
                    f"📂 Section: *{section_name}*\n"
                    f"💰 Price: ₹{price}\n\n"
                    f"This section is paid. Complete payment to access the notes.",
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
        except Exception as exc:
            logger.warning("broadcast_batch failed for chat_id=%s: %s", chat_cid, exc)

        time.sleep(0.1)
