"""
api/routes/webhook.py
~~~~~~~~~~~~~~~~~~~~~
POST /cashfree-webhook
POST /webhook
POST /razorpay-webhook (legacy alias)

Verifies the Cashfree HMAC signature, records the order, and delivers
study materials to the buyer via Telegram.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.instance import bot
from config import ADMIN_ID
from db.queries import async_fetch_subject, async_record_order
from services.cashfree import verify_webhook_signature
from utils.sections import get_sections, section_price

logger = logging.getLogger("unieval")
router = APIRouter()


def _safe_send_message(chat_id: int, text: str, parse_mode: str | None = "HTML", reply_markup=None):
    """Send a Telegram message with HTML formatting and automatic plain-text fallback on error."""
    try:
        return bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception as exc:
        logger.warning(
            "Failed sending message with parse_mode=%s (%s), falling back to plain text",
            parse_mode,
            exc,
        )
        return bot.send_message(chat_id, text, parse_mode=None, reply_markup=reply_markup)


@router.post("/cashfree-webhook")
@router.post("/webhook")
@router.post("/razorpay-webhook")
async def cashfree_webhook(request: Request) -> dict:
    body      = await request.body()
    signature = (
        request.headers.get("x-webhook-signature")
        or request.headers.get("x-razorpay-signature")
        or request.headers.get("signature")
        or ""
    )
    timestamp = request.headers.get("x-webhook-timestamp") or request.headers.get("timestamp") or ""

    logger.info("Incoming webhook signature: %r, timestamp: %r", signature, timestamp)

    if not verify_webhook_signature(body, signature, timestamp):
        logger.warning("Payment webhook: invalid or missing signature.")
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error("Payment webhook: failed to parse JSON — %s", exc)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("type") or payload.get("event")
    logger.info("Payment webhook event received: %s", event_type)

    data = payload.get("data", {})
    notes: dict = {}

    # 1. Cashfree Payment Link event
    if event_type == "PAYMENT_LINK_EVENT":
        link_status = str(data.get("link_status", "")).upper()
        order_status = str(data.get("order", {}).get("transaction_status", "")).upper()
        if link_status != "PAID" and order_status != "SUCCESS":
            logger.info("Cashfree payment link status '%s' / order '%s' ignored.", link_status, order_status)
            return {"status": "ignored", "link_status": link_status, "order_status": order_status}
        notes = (
            data.get("link_notes")
            or data.get("order", {}).get("order_tags")
            or {}
        )

    # 2. Cashfree Payment Success webhook
    elif event_type in ("PAYMENT_SUCCESS_WEBHOOK", "PAYMENT_CHARGES_WEBHOOK"):
        payment_status = str(data.get("payment", {}).get("payment_status", "")).upper()
        if payment_status and payment_status != "SUCCESS":
            logger.info("Cashfree payment status '%s' ignored.", payment_status)
            return {"status": "ignored", "payment_status": payment_status}
        order = data.get("order", {})
        notes = (
            order.get("order_tags")
            or order.get("link_notes")
            or data.get("link_notes")
            or {}
        )

    # 3. Legacy Razorpay event fallback
    elif event_type == "payment_link.paid":
        entity = payload.get("payload", {}).get("payment_link", {}).get("entity", {})
        notes = entity.get("notes", {})

    # 4. Generic fallback: check if notes exist in data
    elif "link_notes" in data or "order_tags" in data.get("order", {}):
        notes = data.get("link_notes") or data.get("order", {}).get("order_tags") or {}

    else:
        logger.info("Webhook event '%s' ignored.", event_type)
        return {"status": "ignored", "event": event_type}

    logger.info("Webhook extracted notes: %s", notes)

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
            sec_name_escaped = html.escape(sec['name'])
            sub_name_escaped = html.escape(subject['name'])
            msg_text = (
                f"🎉 <b>Payment Confirmed!</b>\n\n"
                f"Thank you for purchasing <b>{sec_name_escaped}</b> from <b>{sub_name_escaped}</b>.\n\n"
                f"Tap below to download your section."
            )
            await loop.run_in_executor(
                None,
                lambda: _safe_send_message(target_chat, msg_text, parse_mode="HTML", reply_markup=kb),
            )
        else:
            sub_name_escaped = html.escape(subject['name'])
            msg_text = (
                f"🎉 <b>Payment Confirmed!</b>\n\nThank you for purchasing <b>{sub_name_escaped}</b>.\n\n"
                + (
                    "Your study materials are ready! Select a section below to download: 📚"
                    if has_files
                    else "Files will be available soon. Use /my_notes once ready."
                )
            )
            await loop.run_in_executor(
                None,
                lambda: _safe_send_message(target_chat, msg_text, parse_mode="HTML"),
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
                sec_text = "📂 <b>Choose a section to download:</b>\n<i>(or type /my_notes anytime)</i>"
                await loop.run_in_executor(
                    None,
                    lambda: _safe_send_message(target_chat, sec_text, parse_mode="HTML", reply_markup=kb),
                )

        logger.info("Delivery UI sent to chat_id %s for subject '%s'.", chat_id, subject["name"])

    except Exception as exc:
        logger.error("CRITICAL DELIVERY FAILURE for chat_id %s: %s", chat_id, exc)
        try:
            admin_msg = f"⚠️ DELIVERY FAILURE\n\nchat_id: {chat_id}\nSubject: {subject['name']}\nError: {exc}\n\nPlease deliver manually."
            await loop.run_in_executor(
                None,
                lambda: _safe_send_message(ADMIN_ID, admin_msg, parse_mode=None),
            )
        except Exception:
            pass

    return {"status": "ok"}


def _notify_missing_subject(chat_id: str, subject_id: str) -> None:
    """Notify both the buyer and admin when a paid subject can't be found."""
    try:
        _safe_send_message(
            int(chat_id),
            "✅ Payment received! However, there was a temporary issue retrieving your materials. "
            "Please contact support — you will NOT be charged again.",
            parse_mode=None,
        )
    except Exception:
        pass
    try:
        _safe_send_message(
            ADMIN_ID,
            f"⚠️ DELIVERY FAILURE\n\nPayment received from chat_id {chat_id} but subject_id {subject_id} was not found.\nPlease deliver manually.",
            parse_mode=None,
        )
    except Exception:
        pass


def _notify_missing_section(chat_id: str, subject_name: str, section_idx: int) -> None:
    """Notify both the buyer and admin when a paid section can't be found."""
    try:
        _safe_send_message(
            int(chat_id),
            "✅ Payment received! However, there was a temporary issue retrieving your section. "
            "Please contact support — you will NOT be charged again.",
            parse_mode=None,
        )
    except Exception:
        pass
    try:
        _safe_send_message(
            ADMIN_ID,
            f"⚠️ DELIVERY FAILURE\n\nPayment received from chat_id {chat_id} for {subject_name} but section index {section_idx} was not found.\nPlease deliver manually.",
            parse_mode=None,
        )
    except Exception:
        pass
