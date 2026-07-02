"""
bot/handlers/callbacks.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Single handler for all inline-keyboard callback queries.

Routing is done by matching the `call.data` string prefix.
Each logical section is delimited with a comment block.
"""

from __future__ import annotations

import telebot
from bson import ObjectId
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.instance import bot
from bot.cleanup import send_tracked, sweep
from bot.keyboards import (
    admin_main_keyboard,
    add_note_type_keyboard,
    claim_reward_keyboard,
    sections_keyboard,
    subjects_keyboard,
    view_sections_keyboard,
    purchased_subjects_keyboard,
)
from bot.state import clear_state, get_context, set_state
from bot.handlers.messages import finish_upload, finish_text_upload
from config import ADMIN_ID, STORAGE_GROUP_ID, logger
from db.client import run_async
from db.queries import (
    async_delete_subject,
    async_grant_access,
    async_save_sections,
    async_increment_reward_claims,
    fetch_subject,
    fetch_user_orders,
    fetch_referral_count,
    fetch_reward_claims,
    fetch_all_subjects,
    fetch_all_user_chat_ids,
    get_settings,
    set_promo_message,
    set_referral_threshold,
)
from services.razorpay import create_payment_link
from utils.sections import (
    get_sections,
    has_section_access,
    has_subject_access,
    is_section_free,
    section_price,
    section_item_count,
)


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call: telebot.types.CallbackQuery) -> None:
    cid  = call.message.chat.id
    data = call.data
    bot.answer_callback_query(call.id)

    # ── Noop ──────────────────────────────────────────────────────────────────
    if data == "noop":
        return

    # =========================================================================
    # ADMIN: Add Subject
    # =========================================================================
    elif data == "add_subject":
        if call.from_user.id != ADMIN_ID:
            return
        set_state(cid, "add_subject_name")
        bot.send_message(cid, "📝 Enter the *name* of the new subject:", parse_mode="Markdown")

    # =========================================================================
    # ADMIN: Edit Subject
    # =========================================================================
    elif data == "edit_subject":
        if call.from_user.id != ADMIN_ID:
            return
        bot.send_message(cid, "✏️ Select a subject to edit:", reply_markup=subjects_keyboard("edit_subject_select"))

    elif data.startswith("edit_subject_select:"):
        if call.from_user.id != ADMIN_ID:
            return
        subject_id = data.split(":", 1)[1]
        subject    = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("✏️ Edit Name",  callback_data=f"edit_name:{subject_id}"),
            InlineKeyboardButton("💰 Edit Price", callback_data=f"edit_price:{subject_id}"),
        )
        bot.send_message(
            cid,
            f"Editing *{subject['name']}*. What do you want to change?",
            parse_mode="Markdown",
            reply_markup=kb,
        )

    elif data.startswith("edit_name:"):
        if call.from_user.id != ADMIN_ID:
            return
        set_state(cid, "edit_subject_name", subject_id=data.split(":", 1)[1])
        bot.send_message(cid, "✏️ Enter the new subject name:")

    elif data.startswith("edit_price:"):
        if call.from_user.id != ADMIN_ID:
            return
        set_state(cid, "edit_subject_price", subject_id=data.split(":", 1)[1])
        bot.send_message(cid, "💰 Enter the new price in ₹ (numbers only):")

    # =========================================================================
    # ADMIN: Delete Subject
    # =========================================================================
    elif data == "delete_subject":
        if call.from_user.id != ADMIN_ID:
            return
        bot.send_message(cid, "❌ Select a subject to delete:", reply_markup=subjects_keyboard("delete_confirm"))

    elif data.startswith("delete_confirm:"):
        if call.from_user.id != ADMIN_ID:
            return
        subject_id = data.split(":", 1)[1]
        subject    = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"delete_do:{subject_id}"),
            InlineKeyboardButton("❌ Cancel",       callback_data="noop"),
        )
        bot.send_message(
            cid,
            f"⚠️ Are you sure you want to delete *{subject['name']}*?",
            parse_mode="Markdown",
            reply_markup=kb,
        )

    elif data.startswith("delete_do:"):
        if call.from_user.id != ADMIN_ID:
            return
        subject_id = data.split(":", 1)[1]
        subject    = fetch_subject(subject_id)
        run_async(async_delete_subject(subject_id))
        bot.send_message(cid, f"🗑️ Subject *{subject['name']}* deleted.", parse_mode="Markdown")

    # =========================================================================
    # ADMIN: Manage Sections
    # =========================================================================
    elif data == "manage_sections":
        if call.from_user.id != ADMIN_ID:
            return
        bot.send_message(cid, "📂 Select a subject to manage its sections:",
                         reply_markup=subjects_keyboard("manage_sec_subject"))

    elif data.startswith("manage_sec_subject:"):
        if call.from_user.id != ADMIN_ID:
            return
        subject_id = data.split(":", 1)[1]
        subject    = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        sections = get_sections(subject)
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("➕ Add New Section", callback_data=f"add_sec:{subject_id}"))
        for idx, sec in enumerate(sections):
            item_count = section_item_count(sec)
            access = "FREE" if is_section_free(subject, sec) else f"PAID ₹{section_price(subject, sec)}"
            kb.add(InlineKeyboardButton(
                f"⚙️ {sec['name']} — {access} ({item_count} items)",
                callback_data=f"edit_sec_access:{subject_id}:{idx}",
            ))
            kb.add(InlineKeyboardButton(
                f"🗑️ Delete: {sec['name']} ({item_count} items)",
                callback_data=f"del_sec_confirm:{subject_id}:{idx}",
            ))
        bot.send_message(
            cid,
            f"📂 Sections for *{subject['name']}*:\n\nAdd, delete, or change free/paid access.",
            parse_mode="Markdown",
            reply_markup=kb,
        )

    elif data.startswith("edit_sec_access:"):
        if call.from_user.id != ADMIN_ID:
            return
        _, subject_id, idx_str = data.split(":", 2)
        subject = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        sections = get_sections(subject)
        idx = int(idx_str)
        if idx >= len(sections):
            bot.send_message(cid, "❌ Section not found.")
            return
        sec = sections[idx]
        access = "FREE" if is_section_free(subject, sec) else f"PAID ₹{section_price(subject, sec)}"
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("🆓 Make Free", callback_data=f"sec_make_free:{subject_id}:{idx}"),
            InlineKeyboardButton("💰 Make Paid / Set Price", callback_data=f"sec_set_paid:{subject_id}:{idx}"),
            InlineKeyboardButton("⬅️ Back to Sections", callback_data=f"manage_sec_subject:{subject_id}"),
        )
        bot.send_message(
            cid,
            f"⚙️ *{sec['name']}*\nCurrent access: *{access}*\n\nChoose what to change:",
            parse_mode="Markdown",
            reply_markup=kb,
        )

    elif data.startswith("sec_make_free:"):
        if call.from_user.id != ADMIN_ID:
            return
        _, subject_id, idx_str = data.split(":", 2)
        subject = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        sections = get_sections(subject)
        idx = int(idx_str)
        if idx >= len(sections):
            bot.send_message(cid, "❌ Section not found.")
            return
        sections[idx]["is_free"] = True
        sections[idx]["price"] = 0
        run_async(async_save_sections(subject_id, sections))
        bot.send_message(cid, f"✅ Section *{sections[idx]['name']}* is now FREE.", parse_mode="Markdown")

    elif data.startswith("sec_set_paid:"):
        if call.from_user.id != ADMIN_ID:
            return
        _, subject_id, idx_str = data.split(":", 2)
        set_state(cid, "edit_section_price", subject_id=subject_id, section_idx=int(idx_str))
        bot.send_message(cid, "💰 Enter the section price in ₹ (numbers only):")

    elif data.startswith("add_sec:"):
        if call.from_user.id != ADMIN_ID:
            return
        set_state(cid, "add_section_name", subject_id=data.split(":", 1)[1])
        bot.send_message(
            cid,
            "📝 Enter a name for the new section (e.g. *Unit 1*, *Short Notes*, *PYQs*):",
            parse_mode="Markdown",
        )

    elif data.startswith("del_sec_confirm:"):
        if call.from_user.id != ADMIN_ID:
            return
        _, subject_id, idx_str = data.split(":", 2)
        subject  = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        sections = get_sections(subject)
        idx      = int(idx_str)
        if idx >= len(sections):
            bot.send_message(cid, "❌ Section not found.")
            return
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"del_sec_do:{subject_id}:{idx}"),
            InlineKeyboardButton("❌ Cancel",       callback_data="noop"),
        )
        bot.send_message(
            cid,
            f"⚠️ Delete section *{sections[idx]['name']}* and all its files?",
            parse_mode="Markdown",
            reply_markup=kb,
        )

    elif data.startswith("del_sec_do:"):
        if call.from_user.id != ADMIN_ID:
            return
        _, subject_id, idx_str = data.split(":", 2)
        subject  = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        sections = get_sections(subject)
        idx      = int(idx_str)
        if idx >= len(sections):
            bot.send_message(cid, "❌ Section not found.")
            return
        sec_name = sections[idx]["name"]
        sections.pop(idx)
        run_async(async_save_sections(subject_id, sections))
        bot.send_message(cid, f"🗑️ Section *{sec_name}* deleted.", parse_mode="Markdown")

    # =========================================================================
    # ADMIN: Add File to Section
    # =========================================================================
    elif data == "add_note":
        if call.from_user.id != ADMIN_ID:
            return
        bot.send_message(cid, "📄 Select the subject to add a file to:",
                         reply_markup=subjects_keyboard("add_note_subject"))

    elif data.startswith("add_note_subject:"):
        if call.from_user.id != ADMIN_ID:
            return
        subject_id = data.split(":", 1)[1]
        subject    = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        sections = get_sections(subject)
        if not sections:
            bot.send_message(
                cid,
                f"⚠️ *{subject['name']}* has no sections yet.\n\n"
                "Please add sections first using *Manage Sections*.",
                parse_mode="Markdown",
            )
            return
        bot.send_message(
            cid,
            f"📂 Which section of *{subject['name']}* do you want to add a file to?",
            parse_mode="Markdown",
            reply_markup=sections_keyboard(subject, "add_note_section"),
        )

    elif data.startswith("add_note_section:"):
        if call.from_user.id != ADMIN_ID:
            return
        _, subject_id, idx_str = data.split(":", 2)
        subject  = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        idx      = int(idx_str)
        sections = get_sections(subject)
        if idx >= len(sections):
            bot.send_message(cid, "❌ Section not found.")
            return
        sec_name = sections[idx]["name"]
        bot.send_message(
            cid,
            f"📎 Adding a note to *{sec_name}* of *{subject['name']}*.\n\n"
            "Do you want to upload a file, or send it as a plain text note?",
            parse_mode="Markdown",
            reply_markup=add_note_type_keyboard(subject_id, idx),
        )

    elif data.startswith("add_note_kind:"):
        if call.from_user.id != ADMIN_ID:
            return
        _, kind, subject_id, idx_str = data.split(":", 3)
        idx = int(idx_str)
        subject = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        sections = get_sections(subject)
        if idx >= len(sections):
            bot.send_message(cid, "❌ Section not found.")
            return
        sec_name = sections[idx]["name"]

        if kind == "file":
            set_state(cid, "add_note_upload", subject_id=subject_id, section_idx=idx, saved_count=0)
            bot.send_message(
                cid,
                f"📎 Send files for section *{sec_name}* of *{subject['name']}*.\n\n"
                "You can send *multiple files one by one*. When done, tap *✅ Done* or type `done`.",
                parse_mode="Markdown",
            )
        else:
            set_state(cid, "add_note_text", subject_id=subject_id, section_idx=idx, saved_count=0)
            bot.send_message(
                cid,
                f"📝 Send the text note(s) for section *{sec_name}* of *{subject['name']}*.\n\n"
                "You can send *multiple notes one by one*. When done, tap *✅ Done* or type `done`.",
                parse_mode="Markdown",
            )

    # =========================================================================
    # ADMIN: Upload Done
    # =========================================================================
    elif data.startswith("upload_done_text:"):
        if call.from_user.id != ADMIN_ID:
            return
        _, subject_id, idx_str = data.split(":", 2)
        finish_text_upload(cid, subject_id, int(idx_str))

    elif data.startswith("upload_done:"):
        if call.from_user.id != ADMIN_ID:
            return
        _, subject_id, idx_str = data.split(":", 2)
        finish_upload(cid, subject_id, int(idx_str))

    # =========================================================================
    # ADMIN: Generate Payment Link
    # =========================================================================
    elif data == "gen_link":
        if call.from_user.id != ADMIN_ID:
            return
        bot.send_message(cid, "🔗 Select a subject to generate a payment link for:",
                         reply_markup=subjects_keyboard("gen_link_select"))

    elif data.startswith("gen_link_select:"):
        if call.from_user.id != ADMIN_ID:
            return
        subject_id = data.split(":", 1)[1]
        subject    = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        try:
            url = create_payment_link(
                chat_id=str(ADMIN_ID),
                subject_id=str(subject["_id"]),
                subject_name=subject["name"],
                price_inr=subject["price"],
            )
            bot.send_message(cid, f"🔗 Payment link for *{subject['name']}*:\n\n{url}", parse_mode="Markdown")
        except Exception as exc:
            bot.send_message(cid, f"❌ Failed to create link: {exc}")

    # =========================================================================
    # ADMIN: Grant Access via Mobile
    # =========================================================================
    elif data == "grant_access_mobile":
        if call.from_user.id != ADMIN_ID:
            return
        set_state(cid, "grant_access_mobile")
        bot.send_message(cid, "📱 Enter the user's mobile number (with or without +91):")

    elif data.startswith("grant_sub:"):
        if call.from_user.id != ADMIN_ID:
            return
        subject_id     = data.split(":", 1)[1]
        ctx            = get_context(cid)
        target_chat_id = ctx.get("target_chat_id")

        if not target_chat_id:
            bot.send_message(cid, "❌ Session expired. Please start again with Grant Access.")
            return

        subject = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return

        run_async(async_grant_access(str(target_chat_id), subject_id))
        clear_state(cid)
        bot.send_message(
            cid,
            f"✅ Access granted to `{target_chat_id}` for *{subject['name']}*.",
            parse_mode="Markdown",
        )
        try:
            bot.send_message(
                int(target_chat_id),
                f"🎉 You've been granted access to *{subject['name']}*!\n\nUse /my_notes to download your files.",
                parse_mode="Markdown",
            )
        except Exception as exc:
            bot.send_message(cid, f"⚠️ Could not notify the user directly: {exc}")

    # =========================================================================
    # USER: Buy One Section
    # =========================================================================
    elif data.startswith("buy_section:"):
        _, subject_id, idx_str = data.split(":", 2)
        subject = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return

        sections = get_sections(subject)
        idx = int(idx_str)
        if idx >= len(sections):
            bot.send_message(cid, "❌ Section not found.")
            return

        sec = sections[idx]
        orders = fetch_user_orders(str(cid))
        if has_section_access(orders, subject_id, idx, subject, sec):
            bot.send_message(
                cid,
                f"✅ You already have access to *{sec['name']}*.",
                parse_mode="Markdown",
                reply_markup=view_sections_keyboard(subject, orders),
            )
            return

        price = section_price(subject, sec)
        if price == 0:
            sections[idx]["is_free"] = True
            run_async(async_save_sections(subject_id, sections))
            bot.send_message(
                cid,
                f"🆓 *{sec['name']}* is free. Tap it below to download.",
                parse_mode="Markdown",
                reply_markup=view_sections_keyboard(subject, orders),
            )
            return

        try:
            url = create_payment_link(
                chat_id=str(cid),
                subject_id=subject_id,
                subject_name=subject["name"],
                price_inr=price,
                section_idx=idx,
                section_name=sec["name"],
            )
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("💳 Pay Now", url=url))
            bot.send_message(
                cid,
                f"📚 *{subject['name']}*\n"
                f"📂 Section: *{sec['name']}*\n"
                f"💰 Price: ₹{price}\n\n"
                f"Click the button below to complete your purchase securely:",
                parse_mode="Markdown",
                reply_markup=kb,
            )
        except Exception as exc:
            bot.send_message(cid, f"❌ Could not generate payment link: {exc}")

    # =========================================================================
    # USER: Buy Subject
    # =========================================================================
    elif data.startswith("buy:"):
        subject_id = data.split(":", 1)[1]
        subject    = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return

        existing = fetch_user_orders(str(cid))
        already_has_access = has_subject_access(existing, subject_id)
        sections = get_sections(subject)

        if sections:
            kb = view_sections_keyboard(subject, existing)
            if subject.get("price", 0) > 0 and not already_has_access:
                kb.add(InlineKeyboardButton("💳 Buy Full Subject", callback_data=f"buy_full_subject:{subject_id}"))
            kb.add(InlineKeyboardButton("📂 View Purchased Notes", callback_data="view_purchased"))
            bot.send_message(
                cid,
                f"📚 *{subject['name']}*\n\nChoose a section below:",
                parse_mode="Markdown",
                reply_markup=kb,
            )
            return

        # ── FREE subject (price = 0) ──────────────────────────────────────
        if subject.get("price", 0) == 0:
            if not already_has_access and not sections:
                run_async(async_grant_access(str(cid), subject_id))

            if not sections:
                kb = InlineKeyboardMarkup(row_width=1)
                kb.add(InlineKeyboardButton("📚 Access Your All Notes", callback_data="view_purchased"))
                bot.send_message(
                    cid,
                    f"🎉 *{subject['name']}* is *FREE!*\n\n"
                    f"✅ Access granted! Files will be uploaded soon — check back later.\n"
                    f"_(or type /mynotes)_",
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
                return

            # Show sections directly — no extra button click needed
            kb = view_sections_keyboard(subject)
            kb.add(InlineKeyboardButton("📚 Access Your All Notes", callback_data="view_purchased"))
            bot.send_message(
                cid,
                f"🎉 *{subject['name']}* is *FREE!*\n\n"
                f"Choose a section below. Free sections open directly; paid sections require payment.\n"
                f"_(or type /mynotes)_",
                parse_mode="Markdown",
                reply_markup=kb,
            )
            return

        if already_has_access:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("📂 Access Your Notes", callback_data="view_purchased"))
            bot.send_message(
                cid,
                f"✅ You already have access to *{subject['name']}*!\n\n"
                f"📖 Access your All Unlocked Notes Here 👇\n"
                f"_(or type /mynotes)_",
                parse_mode="Markdown",
                reply_markup=kb,
            )
            return

        # ── PAID subject ──────────────────────────────────────────────────
        try:
            url = create_payment_link(
                chat_id=str(cid),
                subject_id=subject_id,
                subject_name=subject["name"],
                price_inr=subject["price"],
            )
            sections  = get_sections(subject)
            sec_names = ", ".join(s["name"] for s in sections) if sections else "Files coming soon"
            kb        = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("💳 Pay Now", url=url))
            bot.send_message(
                cid,
                f"📚 *{subject['name']}*\n"
                f"💰 Price: ₹{subject['price']}\n"
                f"📂 Sections: _{sec_names}_\n\n"
                f"Click the button below to complete your purchase securely:",
                parse_mode="Markdown",
                reply_markup=kb,
            )
        except Exception as exc:
            bot.send_message(cid, f"❌ Could not generate payment link: {exc}")

    elif data.startswith("buy_full_subject:"):
        subject_id = data.split(":", 1)[1]
        subject = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return

        existing = fetch_user_orders(str(cid))
        if has_subject_access(existing, subject_id):
            bot.send_message(cid, f"✅ You already have access to *{subject['name']}*.", parse_mode="Markdown")
            return

        try:
            url = create_payment_link(
                chat_id=str(cid),
                subject_id=subject_id,
                subject_name=subject["name"],
                price_inr=subject["price"],
            )
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("💳 Pay Now", url=url))
            bot.send_message(
                cid,
                f"📚 *{subject['name']}*\n"
                f"💰 Full Subject Price: ₹{subject['price']}\n\n"
                f"Click the button below to unlock all sections:",
                parse_mode="Markdown",
                reply_markup=kb,
            )
        except Exception as exc:
            bot.send_message(cid, f"❌ Could not generate payment link: {exc}")

    # =========================================================================
    # USER: View Purchased Notes
    # =========================================================================
    elif data == "view_purchased":
        orders = fetch_user_orders(str(cid))
        if not orders:
            send_tracked(bot, cid, "❌ You haven't purchased any subjects yet.\n\nUse /start to browse.")
            return
        send_tracked(
            bot, cid,
            "📂 *Access Your All Notes:*\n\nSelect a subject to view its sections:\n_(or type /mynotes anytime)_",
            parse_mode="Markdown",
            reply_markup=purchased_subjects_keyboard(orders),
        )

    # =========================================================================
    # USER: View Sections
    # =========================================================================
    elif data.startswith("view_sections:"):
        subject_id = data.split(":", 1)[1]

        orders = fetch_user_orders(str(cid))
        subject = fetch_subject(subject_id)

        # Only legacy flat free subjects get whole-subject access. Sectioned free
        # subjects may still contain paid sections, so do not unlock all sections.
        if subject and subject.get("price", 0) == 0 and not get_sections(subject) and not any(o["subject_id"] == subject_id for o in orders):
            run_async(async_grant_access(str(cid), subject_id))
            orders = fetch_user_orders(str(cid))  # refresh after grant

        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return

        sections = get_sections(subject)
        if not sections:
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("📚 Access Your All Notes", callback_data="view_purchased"))
            send_tracked(
                bot, cid,
                f"⚠️ *{subject['name']}* has no files uploaded yet. Check back soon!\n\n"
                f"_(or type /mynotes to see all your subjects)_",
                parse_mode="Markdown",
                reply_markup=kb,
            )
            return

        kb = view_sections_keyboard(subject, orders)
        kb.add(InlineKeyboardButton("⬅️ All My Notes", callback_data="view_purchased"))
        send_tracked(
            bot, cid,
            f"📚 *{subject['name']}*\n\nChoose a section to download:\n_(or type /mynotes to see all subjects)_",
            parse_mode="Markdown",
            reply_markup=kb,
        )

    # =========================================================================
    # USER: Download Section
    # =========================================================================
    elif data.startswith("download_section:"):
        _, subject_id, idx_str = data.split(":", 2)

        subject  = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return
        sections = get_sections(subject)
        idx      = int(idx_str)

        if idx >= len(sections):
            bot.send_message(cid, "❌ Section not found.")
            return

        sec        = sections[idx]
        file_ids   = sec.get("file_ids", [])
        text_notes = sec.get("text_notes", [])
        orders     = fetch_user_orders(str(cid))

        if not has_section_access(orders, subject_id, idx, subject, sec):
            price = section_price(subject, sec)
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton(f"💳 Pay ₹{price}", callback_data=f"buy_section:{subject_id}:{idx}"))
            bot.send_message(
                cid,
                f"🔒 *{sec['name']}* is a paid section.\n\nPlease complete payment to download it.",
                parse_mode="Markdown",
                reply_markup=kb,
            )
            return

        if not file_ids and not text_notes:
            bot.send_message(cid, f"⚠️ No notes in *{sec['name']}* yet. Check back soon!", parse_mode="Markdown")
            return

        total = len(file_ids) + len(text_notes)
        send_tracked(
            bot, cid,
            f"📤 Sending *{sec['name']}* ({total} item{'s' if total != 1 else ''})…",
            parse_mode="Markdown",
        )
        for msg_id_str in file_ids:
            try:
                bot.copy_message(
                    chat_id=cid,
                    from_chat_id=STORAGE_GROUP_ID,
                    message_id=int(msg_id_str),
                )
            except Exception as exc:
                logger.error("Failed to send file %s to %s: %s", msg_id_str, cid, exc)
        for note_text in text_notes:
            try:
                bot.send_message(cid, note_text)
            except Exception as exc:
                logger.error("Failed to send text note to %s: %s", cid, exc)

        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("📚 Access Your All Purchased Notes Here", callback_data="view_purchased"),
        )
        sweep(bot, cid)
        bot.send_message(
            cid,
            f"✅ *{sec['name']}* sent successfully!\n\n"
            f"📖 Access your All Purchased Notes Here 👇\n_(or type /mynotes)_",
            parse_mode="Markdown",
            reply_markup=kb,
        )

    # =========================================================================
    # Legacy: download all (no section)
    # =========================================================================
    elif data.startswith("download:"):
        subject_id = data.split(":", 1)[1]

        orders = fetch_user_orders(str(cid))
        if not has_subject_access(orders, subject_id):
            bot.send_message(cid, "⛔ You don't have access to this subject.")
            return

        subject  = fetch_subject(subject_id)
        sections = get_sections(subject)

        if len(sections) > 1:
            bot.send_message(
                cid,
                f"📚 *{subject['name']}*\n\nChoose a section to download:",
                parse_mode="Markdown",
                reply_markup=view_sections_keyboard(subject, orders),
            )
        else:
            if sections and not has_section_access(orders, subject_id, 0, subject, sections[0]):
                bot.send_message(cid, "⛔ You don't have access to this section.")
                return
            all_ids   = sections[0].get("file_ids", []) if sections else []
            all_texts = sections[0].get("text_notes", []) if sections else []
            if not all_ids and not all_texts:
                bot.send_message(cid, "⚠️ No notes uploaded yet.")
                return
            send_tracked(bot, cid, f"📤 Sending *{subject['name']}* notes…", parse_mode="Markdown")
            for msg_id_str in all_ids:
                try:
                    bot.copy_message(
                        chat_id=cid,
                        from_chat_id=STORAGE_GROUP_ID,
                        message_id=int(msg_id_str),
                    )
                except Exception as exc:
                    logger.error("Failed to send file %s to %s: %s", msg_id_str, cid, exc)
            for note_text in all_texts:
                try:
                    bot.send_message(cid, note_text)
                except Exception as exc:
                    logger.error("Failed to send text note to %s: %s", cid, exc)
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("📚 Access Your All Purchased Notes Here", callback_data="view_purchased"))
            sweep(bot, cid)
            bot.send_message(
                cid,
                f"✅ Notes sent!\n\n📖 Access your All Purchased Notes Here 👇\n_(or type /mynotes)_",
                parse_mode="Markdown",
                reply_markup=kb,
            )

    # =========================================================================
    # USER: Claim referral reward — pick any subject to unlock for free
    # =========================================================================
    elif data == "claim_reward":
        threshold = get_settings().get("referral_threshold", 5)
        count     = fetch_referral_count(str(cid))
        claims    = fetch_reward_claims(str(cid))
        available = max(0, (count // threshold) - claims)
        if available <= 0:
            bot.send_message(
                cid,
                f"You don't have a free unlock available right now.\n\n"
                f"Invite {threshold} friends (they must register) to earn one — check /myrefs.",
            )
            return
        send_tracked(
            bot, cid,
            "🎁 Choose the subject you want to unlock for free:",
            reply_markup=subjects_keyboard("claim_subject"),
        )

    elif data.startswith("claim_subject:"):
        subject_id = data.split(":", 1)[1]
        threshold  = get_settings().get("referral_threshold", 5)
        count      = fetch_referral_count(str(cid))
        claims     = fetch_reward_claims(str(cid))
        available  = max(0, (count // threshold) - claims)

        if available <= 0:
            bot.send_message(cid, "❌ No free unlocks available right now.")
            return

        subject = fetch_subject(subject_id)
        if not subject:
            bot.send_message(cid, "❌ Subject not found.")
            return

        run_async(async_grant_access(str(cid), subject_id))
        run_async(async_increment_reward_claims(str(cid)))
        sweep(bot, cid)
        bot.send_message(
            cid,
            f"🎉 *{subject['name']}* unlocked for free — enjoy!\n\nUse /my_notes to access it.",
            parse_mode="Markdown",
        )

    # =========================================================================
    # ADMIN: Broadcast a message to every registered user (one-time blast)
    # =========================================================================
    elif data == "broadcast_message":
        if call.from_user.id != ADMIN_ID:
            return
        set_state(cid, "broadcast_message")
        bot.send_message(cid, "📢 Send the message you want to broadcast to *all* users:", parse_mode="Markdown")

    # =========================================================================
    # ADMIN: Set the persistent promo footer shown on /start & /get
    # =========================================================================
    elif data == "set_promo":
        if call.from_user.id != ADMIN_ID:
            return
        current = get_settings().get("promo_message", "")
        set_state(cid, "set_promo")
        bot.send_message(
            cid,
            f"📌 Current promo footer:\n_{current or '(none set)'}_\n\n"
            "Send the new promo text (e.g. your WhatsApp community link). "
            "Send `clear` to remove it.",
            parse_mode="Markdown",
        )

    # =========================================================================
    # ADMIN: Set referral threshold
    # =========================================================================
    elif data == "set_ref_threshold":
        if call.from_user.id != ADMIN_ID:
            return
        current = get_settings().get("referral_threshold", 5)
        set_state(cid, "set_ref_threshold")
        bot.send_message(
            cid,
            f"🎯 Current referral threshold: *{current}* friends per free unlock.\n\n"
            "Send the new number:",
            parse_mode="Markdown",
        )
