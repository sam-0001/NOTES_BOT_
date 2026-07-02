"""
bot/handlers/messages.py
~~~~~~~~~~~~~~~~~~~~~~~~
Handles all non-command messages:
  - Mobile-number registration (fallback to contact share)
  - Admin state-machine steps (text input, file uploads)
"""

from __future__ import annotations

import threading

import telebot
from telebot.types import ReplyKeyboardRemove

from bot.instance import bot
from bot.cleanup import send_tracked, sweep
from bot.keyboards import subjects_keyboard, upload_done_keyboard, upload_done_text_keyboard
from bot.state import clear_state, get_context, get_state, set_state, pop_pending_referral
from config import ADMIN_ID, STORAGE_GROUP_ID, logger
from db.client import run_async
from db.queries import (
    async_insert_subject,
    async_push_file_to_section,
    async_push_text_to_section,
    async_push_section,
    async_save_sections,
    async_update_subject_name,
    async_update_subject_price,
    async_upsert_user,
    async_record_referral,
    fetch_subject,
    fetch_user_by_chat,
    fetch_user_by_mobile,
    fetch_all_user_chat_ids,
    set_promo_message,
    set_referral_threshold,
)
from services.broadcast import broadcast_batch
from utils.sections import get_sections


# ---------------------------------------------------------------------------
# Upload-done helper (shared with callback handler)
# ---------------------------------------------------------------------------

def finish_upload(cid: int, subject_id: str, section_idx: int) -> None:
    """Called when admin taps Done or types 'done' – broadcasts the new files."""
    ctx         = get_context(cid)
    saved_count = ctx.get("saved_count", 0)
    clear_state(cid)
    sweep(bot, cid)

    subject = fetch_subject(subject_id)
    if not subject:
        bot.send_message(cid, "❌ Subject not found.")
        return

    sections = get_sections(subject)
    if section_idx >= len(sections):
        bot.send_message(cid, "❌ Section not found.")
        return

    section      = sections[section_idx]
    section_name = section["name"]
    file_ids     = section.get("file_ids", [])

    if saved_count == 0:
        bot.send_message(cid, "ℹ️ No files were uploaded. Session closed.")
        return

    bot.send_message(
        cid,
        f"✅ *Upload complete!* {saved_count} file{'s' if saved_count != 1 else ''} saved "
        f"in *{section_name}* of *{subject['name']}*.\n\n📡 Broadcasting to past buyers…",
        parse_mode="Markdown",
    )

    new_file_ids = file_ids[-saved_count:]
    threading.Thread(
        target=broadcast_batch,
        args=(subject_id, section_name, new_file_ids, section_idx),
        daemon=True,
    ).start()


def finish_text_upload(cid: int, subject_id: str, section_idx: int) -> None:
    """Called when admin taps Done or types 'done' after adding text notes."""
    ctx         = get_context(cid)
    saved_count = ctx.get("saved_count", 0)
    clear_state(cid)
    sweep(bot, cid)

    subject = fetch_subject(subject_id)
    if not subject:
        bot.send_message(cid, "❌ Subject not found.")
        return

    sections = get_sections(subject)
    if section_idx >= len(sections):
        bot.send_message(cid, "❌ Section not found.")
        return

    section      = sections[section_idx]
    section_name = section["name"]
    text_notes   = section.get("text_notes", [])

    if saved_count == 0:
        bot.send_message(cid, "ℹ️ No text notes were added. Session closed.")
        return

    bot.send_message(
        cid,
        f"✅ *Upload complete!* {saved_count} text note{'s' if saved_count != 1 else ''} saved "
        f"in *{section_name}* of *{subject['name']}*.\n\n📡 Broadcasting to past buyers…",
        parse_mode="Markdown",
    )

    new_texts = text_notes[-saved_count:]
    threading.Thread(
        target=broadcast_batch,
        args=(subject_id, section_name, [], section_idx, new_texts),
        daemon=True,
    ).start()


# ---------------------------------------------------------------------------
# Master message handler
# ---------------------------------------------------------------------------

@bot.message_handler(content_types=["text", "document", "photo"])
def handle_message(message: telebot.types.Message) -> None:
    cid = message.chat.id

    # ── Mobile-number registration fallback ──────────────────────────────────
    if message.content_type == "text" and message.text:
        digits = message.text.strip().replace(" ", "").replace("+", "").replace("-", "")
        if digits.isdigit() and 10 <= len(digits) <= 15:
            if not fetch_user_by_chat(str(cid)):
                is_new = run_async(async_upsert_user(str(cid), f"+{digits}"))
                if is_new:
                    ref_code = pop_pending_referral(cid)
                    if ref_code:
                        credited = run_async(async_record_referral(ref_code, str(cid)))
                        if credited:
                            try:
                                bot.send_message(
                                    int(ref_code),
                                    "🎉 Someone just joined using your referral link!\n"
                                    "Use /myrefs to check your progress.",
                                )
                            except Exception:
                                pass
                bot.send_message(cid, "✅ Registration successful!", reply_markup=ReplyKeyboardRemove())
                # Trigger /start flow by re-using the handler
                from bot.handlers.commands import cmd_start
                cmd_start(message)
                return

    # ── Admin-only state machine ─────────────────────────────────────────────
    state = get_state(cid)
    if not state or message.from_user.id != ADMIN_ID:
        return

    ctx = get_context(cid)

    # ── Add subject: name step ───────────────────────────────────────────────
    if state == "add_subject_name":
        name = message.text.strip()
        set_state(cid, "add_subject_price", name=name)
        bot.send_message(cid, f"Got it: *{name}*\n\nNow enter the price in ₹ (numbers only):", parse_mode="Markdown")

    elif state == "add_subject_price":
        if not message.text.strip().isdigit():
            bot.send_message(cid, "⚠️ Please enter a valid number for the price.")
            return
        price = int(message.text.strip())
        name  = ctx["name"]
        run_async(async_insert_subject(name, price))
        clear_state(cid)
        bot.send_message(
            cid,
            f"✅ Subject *{name}* added at ₹{price}.\n\n"
            "Now use *Manage Sections* to add sections like 'Unit 1', 'Short Notes', etc.",
            parse_mode="Markdown",
        )

    # ── Edit subject ─────────────────────────────────────────────────────────
    elif state == "edit_subject_name":
        run_async(async_update_subject_name(ctx["subject_id"], message.text.strip()))
        clear_state(cid)
        bot.send_message(cid, f"✅ Subject name updated to *{message.text.strip()}*.", parse_mode="Markdown")

    elif state == "edit_subject_price":
        if not message.text.strip().isdigit():
            bot.send_message(cid, "⚠️ Please enter a valid number for the price.")
            return
        new_price = int(message.text.strip())
        run_async(async_update_subject_price(ctx["subject_id"], new_price))
        clear_state(cid)
        bot.send_message(cid, f"✅ Subject price updated to ₹{new_price}.", parse_mode="Markdown")

    elif state == "edit_section_price":
        if not message.text.strip().isdigit():
            bot.send_message(cid, "⚠️ Please enter a valid number for the section price.")
            return
        subject_id = ctx["subject_id"]
        section_idx = ctx["section_idx"]
        subject = fetch_subject(subject_id)
        if not subject:
            clear_state(cid)
            bot.send_message(cid, "❌ Subject not found.")
            return
        sections = get_sections(subject)
        if section_idx >= len(sections):
            clear_state(cid)
            bot.send_message(cid, "❌ Section not found.")
            return
        price = int(message.text.strip())
        sections[section_idx]["is_free"] = price == 0
        sections[section_idx]["price"] = price
        run_async(async_save_sections(subject_id, sections))
        clear_state(cid)
        access = "FREE" if price == 0 else f"PAID at ₹{price}"
        bot.send_message(
            cid,
            f"✅ Section *{sections[section_idx]['name']}* is now *{access}*.",
            parse_mode="Markdown",
        )

    # ── Add section name ─────────────────────────────────────────────────────
    elif state == "add_section_name":
        section_name = message.text.strip()
        subject_id   = ctx["subject_id"]
        run_async(async_push_section(subject_id, section_name))
        clear_state(cid)
        subject = fetch_subject(subject_id)
        bot.send_message(
            cid,
            f"✅ Section *{section_name}* added to *{subject['name']}*!\n\n"
            "Now use *Add File to Section* to upload files into it.",
            parse_mode="Markdown",
        )

    # ── Grant access: mobile lookup ──────────────────────────────────────────
    elif state == "grant_access_mobile":
        raw      = message.text.strip().replace(" ", "")
        clean    = raw.replace("+", "")
        variants = [clean, f"+{clean}", f"+91{clean[-10:]}", clean[-10:]]

        user = None
        for variant in variants:
            user = fetch_user_by_mobile(variant)
            if user:
                break

        if not user:
            bot.send_message(
                cid,
                "❌ User not found. Ask them to send their mobile number in the chat to register."
            )
            return

        set_state(cid, "grant_access_subject", target_chat_id=user["chat_id"])
        bot.send_message(
            cid,
            "✅ Found user! Select the subject to grant access to:",
            reply_markup=subjects_keyboard("grant_sub"),
        )

    # ── Admin: broadcast a one-time message to every registered user ───────────
    elif state == "broadcast_message":
        clear_state(cid)
        text = message.text
        if not text:
            bot.send_message(cid, "⚠️ Please send a text message to broadcast.")
            return
        chat_ids = fetch_all_user_chat_ids()
        bot.send_message(cid, f"📡 Broadcasting to {len(chat_ids)} users…")

        def _do_broadcast():
            sent = 0
            for target in chat_ids:
                try:
                    bot.send_message(int(target), text)
                    sent += 1
                except Exception as exc:
                    logger.warning("Broadcast failed for %s: %s", target, exc)
            try:
                bot.send_message(cid, f"✅ Broadcast finished. Delivered to {sent}/{len(chat_ids)} users.")
            except Exception:
                pass

        threading.Thread(target=_do_broadcast, daemon=True).start()

    # ── Admin: set persistent promo footer ──────────────────────────────────
    elif state == "set_promo":
        clear_state(cid)
        text = message.text.strip() if message.text else ""
        if text.lower() == "clear":
            set_promo_message("")
            bot.send_message(cid, "✅ Promo footer cleared.")
        else:
            set_promo_message(text)
            bot.send_message(cid, f"✅ Promo footer updated:\n\n📣 {text}")

    # ── Admin: set referral threshold ───────────────────────────────────────
    elif state == "set_ref_threshold":
        if not message.text or not message.text.strip().isdigit():
            bot.send_message(cid, "⚠️ Please enter a valid whole number.")
            return
        n = int(message.text.strip())
        if n < 1:
            bot.send_message(cid, "⚠️ Threshold must be at least 1.")
            return
        clear_state(cid)
        set_referral_threshold(n)
        bot.send_message(cid, f"✅ Referral threshold set to *{n}* friends per free unlock.", parse_mode="Markdown")

    # ── Text-note upload loop ────────────────────────────────────────────────
    elif state == "add_note_text":
        subject_id  = ctx["subject_id"]
        section_idx = ctx["section_idx"]
        subject     = fetch_subject(subject_id)

        if message.content_type == "text" and message.text and message.text.strip().lower() == "done":
            finish_text_upload(cid, subject_id, section_idx)
            return

        if message.content_type != "text" or not message.text:
            bot.send_message(
                cid,
                "⚠️ Please send the note as plain text.\n\nWhen finished, tap *✅ Done* or type `done`.",
                parse_mode="Markdown",
            )
            return

        run_async(async_push_text_to_section(subject_id, section_idx, message.text))

        saved_count  = ctx.get("saved_count", 0) + 1
        section_name = subject["sections"][section_idx]["name"]

        set_state(cid, "add_note_text",
                  subject_id=subject_id,
                  section_idx=section_idx,
                  saved_count=saved_count)

        bot.send_message(
            cid,
            f"✅ *Note {saved_count} saved* in *{section_name}*.\n\n"
            "Send the next note, or tap Done when finished.",
            parse_mode="Markdown",
            reply_markup=upload_done_text_keyboard(subject_id, section_idx, saved_count),
        )

    # ── File upload loop ─────────────────────────────────────────────────────
    elif state == "add_note_upload":
        subject_id  = ctx["subject_id"]
        section_idx = ctx["section_idx"]
        subject     = fetch_subject(subject_id)

        # "done" text shortcut
        if message.content_type == "text" and message.text and message.text.strip().lower() == "done":
            finish_upload(cid, subject_id, section_idx)
            return

        if not (message.document or message.photo):
            bot.send_message(
                cid,
                "⚠️ Please send a PDF or image file.\n\n"
                "When finished, tap *✅ Done* or type `done`.",
                parse_mode="Markdown",
            )
            return

        bot.send_message(cid, "⏳ Uploading to storage…")

        try:
            storage_msg     = bot.copy_message(
                chat_id=STORAGE_GROUP_ID,
                from_chat_id=cid,
                message_id=message.message_id,
            )
            file_message_id = str(storage_msg.message_id)
        except Exception as exc:
            bot.send_message(cid, f"❌ Failed to copy to storage group: {exc}")
            return  # keep state open so admin can retry

        run_async(async_push_file_to_section(subject_id, section_idx, file_message_id))

        saved_count  = ctx.get("saved_count", 0) + 1
        section_name = subject["sections"][section_idx]["name"]

        set_state(cid, "add_note_upload",
                  subject_id=subject_id,
                  section_idx=section_idx,
                  saved_count=saved_count)

        bot.send_message(
            cid,
            f"✅ *File {saved_count} saved* in *{section_name}*.\n\n"
            "Send the next file, or tap Done when finished.",
            parse_mode="Markdown",
            reply_markup=upload_done_keyboard(subject_id, section_idx, saved_count),
        )
