"""
api/routes/webhook.py
~~~~~~~~~~~~~~~~~~~~~
POST /razorpay-webhook

Verifies the Razorpay HMAC signature, records the order, and delivers
study materials to the buyer via Telegram.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.instance import bot
from config import ADMIN_ID
from db.queries import async_fetch_subject, async_record_order
from services.razorpay import verify_webhook_signature
from utils.sections import get_sections, section_price

logger = logging.getLogger("unieval")
router = APIRouter()


@router.post("/razorpay-webhook")
async def razorpay_webhook(request: Request) -> dict:
    body      = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    if not verify_webhook_signature(body, signature):
        logger.warning("Razorpay webhook: invalid signature received.")
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error("Razorpay webhook: failed to parse JSON — %s", exc)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event")
    logger.info("Razorpay webhook event: %s", event)

    if event != "payment_link.paid":
        return {"status": "ignored", "event": event}

    entity = payload["payload"]["payment_link"]["entity"]
    notes  = entity.get("notes", {})
    logger.info("Webhook notes: %s", notes)

    if "chat_id" not in notes or "subject_id" not in notes:
        return {"status": "ignored_safely", "message": "Missing required notes fields"}

    chat_id     = str(notes["chat_id"]).strip()
    subject_id  = str(notes["subject_id"]).strip()
    section_idx = None
    if notes.get("section_idx") not in (None, ""):
        try:
            section_idx = int(notes["section_idx"])
        except (TypeError, ValueError):
            logger.error("Payment received with invalid section_idx: %r", notes.get("section_idx"))
            return {"status": "error", "detail": "invalid_section_idx"}
    logger.info(
        "Processing payment — chat_id: %r, subject_id: %r, section_idx: %r",
        chat_id,
        subject_id,
        section_idx,
    )

    subject = await async_fetch_subject(subject_id)
    if subject is None:
        logger.error("Payment received but subject_id %r not found. chat_id=%r.", subject_id, chat_id)
        _notify_missing_subject(chat_id, subject_id)
        return {"status": "error", "detail": "subject_not_found"}

    sections  = get_sections(subject)
    if section_idx is not None and section_idx >= len(sections):
        logger.error("Payment received but section_idx %r not found for subject %r.", section_idx, subject_id)
        _notify_missing_section(chat_id, subject["name"], section_idx)
        return {"status": "error", "detail": "section_not_found"}

    await async_record_order(chat_id, subject_id, section_idx)
    logger.info(
        "Order recorded — chat_id: %s, subject: %s, section_idx: %r",
        chat_id,
        subject["name"],
        section_idx,
    )

    has_files = any(len(s.get("file_ids", [])) > 0 for s in sections)
    loop      = asyncio.get_event_loop()

    try:
        target_chat = int(chat_id)

        if section_idx is not None:
            sec = sections[section_idx]
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton(
                f"📂 Download {sec['name']}",
                callback_data=f"download_section:{subject_id}:{section_idx}",
            ))
            kb.add(InlineKeyboardButton("📚 Access Your All Purchased Notes Here", callback_data="view_purchased"))
            await loop.run_in_executor(
                None,
                lambda: bot.send_message(
                    target_chat,
                    f"🎉 *Payment Confirmed!*\n\n"
                    f"Thank you for purchasing *{sec['name']}* from *{subject['name']}*.\n\n"
                    f"Tap below to download your section.",
                    parse_mode="Markdown",
                    reply_markup=kb,
                ),
            )
        else:
            await loop.run_in_executor(
                None,
                lambda: bot.send_message(
                    target_chat,
                    f"🎉 *Payment Confirmed!*\n\nThank you for purchasing *{subject['name']}*.\n\n"
                    + (
                        "Your study materials are ready! Select a section below to download: 📚"
                        if has_files
                        else "Files will be available soon. Use /my_notes once ready."
                    ),
                    parse_mode="Markdown",
                ),
            )

            if has_files and sections:
                kb = InlineKeyboardMarkup(row_width=1)
                for idx, sec in enumerate(sections):
                    file_count = len(sec.get("file_ids", []))
                    if file_count > 0:
                        price = section_price(subject, sec)
                        kb.add(InlineKeyboardButton(
                            f"📂 {sec['name']}  ({file_count} file{'s' if file_count != 1 else ''}, ₹{price})",
                            callback_data=f"download_section:{subject_id}:{idx}",
                        ))
                kb.add(InlineKeyboardButton("📚 Access Your All Purchased Notes Here", callback_data="view_purchased"))
                await loop.run_in_executor(
                    None,
                    lambda: bot.send_message(
                        target_chat,
                        f"📂 *Choose a section to download:*\n_(or type /mynotes anytime)_",
                        parse_mode="Markdown",
                        reply_markup=kb,
                    ),
                )

        logger.info("Delivery UI sent to chat_id %s for subject '%s'.", chat_id, subject["name"])

    except Exception as exc:
        logger.error("CRITICAL DELIVERY FAILURE for chat_id %s: %s", chat_id, exc)
        try:
            await loop.run_in_executor(
                None,
                lambda: bot.send_message(
                    ADMIN_ID,
                    f"⚠️ *DELIVERY FAILURE*\n\n"
                    f"chat_id: `{chat_id}`\nSubject: `{subject['name']}`\nError: `{exc}`\n\n"
                    f"Please deliver manually.",
                    parse_mode="Markdown",
                ),
            )
        except Exception:
            pass

    return {"status": "ok"}


def _notify_missing_subject(chat_id: str, subject_id: str) -> None:
    """Notify both the buyer and admin when a paid subject can't be found."""
    try:
        bot.send_message(
            int(chat_id),
            "✅ Payment received! However, there was a temporary issue retrieving your materials. "
            "Please contact support — you will NOT be charged again.",
        )
    except Exception:
        pass
    try:
        bot.send_message(
            ADMIN_ID,
            f"⚠️ *DELIVERY FAILURE*\n\n"
            f"Payment received from chat_id `{chat_id}` but subject_id `{subject_id}` "
            f"was not found in the database.\nPlease deliver manually.",
            parse_mode="Markdown",
        )
    except Exception:
        pass


def _notify_missing_section(chat_id: str, subject_name: str, section_idx: int) -> None:
    """Notify both the buyer and admin when a paid section can't be found."""
    try:
        bot.send_message(
            int(chat_id),
            "✅ Payment received! However, there was a temporary issue retrieving your section. "
            "Please contact support — you will NOT be charged again.",
        )
    except Exception:
        pass
    try:
        bot.send_message(
            ADMIN_ID,
            f"⚠️ *DELIVERY FAILURE*\n\n"
            f"Payment received from chat_id `{chat_id}` for `{subject_name}` "
            f"but section index `{section_idx}` was not found.\nPlease deliver manually.",
            parse_mode="Markdown",
        )
    except Exception:
        pass
