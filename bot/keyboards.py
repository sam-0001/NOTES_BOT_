"""
bot/keyboards.py
~~~~~~~~~~~~~~~~
All InlineKeyboardMarkup / ReplyKeyboardMarkup factory functions.
Keeps handler code clean – handlers just call a builder and send.
"""

from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from db.queries import fetch_all_subjects
from utils.sections import get_sections, has_section_access, section_price, section_item_count


# ---------------------------------------------------------------------------
# Admin keyboards
# ---------------------------------------------------------------------------

def admin_main_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("➕ Add Subject",             callback_data="add_subject"),
        InlineKeyboardButton("✏️ Edit Subject",            callback_data="edit_subject"),
        InlineKeyboardButton("❌ Delete Subject",          callback_data="delete_subject"),
        InlineKeyboardButton("📂 Manage Sections",         callback_data="manage_sections"),
        InlineKeyboardButton("📄 Add Note to Section",     callback_data="add_note"),
        InlineKeyboardButton("🔗 Generate Payment Link",   callback_data="gen_link"),
        InlineKeyboardButton("🔑 Grant Access via Mobile", callback_data="grant_access_mobile"),
        InlineKeyboardButton("📢 Broadcast Message",       callback_data="broadcast_message"),
        InlineKeyboardButton("📌 Set Promo Footer",        callback_data="set_promo"),
        InlineKeyboardButton("🎯 Set Referral Threshold",  callback_data="set_ref_threshold"),
    )
    return kb


def add_note_type_keyboard(subject_id: str, section_idx: int) -> InlineKeyboardMarkup:
    """Choose whether the admin is adding a file or a plain text note."""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📄 Upload File(s)", callback_data=f"add_note_kind:file:{subject_id}:{section_idx}"),
        InlineKeyboardButton("📝 Send as Text",    callback_data=f"add_note_kind:text:{subject_id}:{section_idx}"),
    )
    return kb


def claim_reward_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("🎁 Claim Your Free Subject", callback_data="claim_reward"))
    return kb


def subjects_keyboard(prefix: str) -> InlineKeyboardMarkup:
    """List all subjects; each button sends `<prefix>:<subject_id>`."""
    kb   = InlineKeyboardMarkup(row_width=1)
    subs = fetch_all_subjects()
    if not subs:
        kb.add(InlineKeyboardButton("(no subjects yet)", callback_data="noop"))
        return kb
    for s in subs:
        price = s.get("price", 0)
        label = f"🆓 {s['name']} — FREE" if price == 0 else f"{s['name']} – ₹{price}"
        kb.add(InlineKeyboardButton(label, callback_data=f"{prefix}:{str(s['_id'])}"))
    return kb


def sections_keyboard(subject: dict, prefix: str) -> InlineKeyboardMarkup:
    """List all sections of a subject; each button sends `<prefix>:<subject_id>:<idx>`."""
    kb         = InlineKeyboardMarkup(row_width=1)
    sections   = get_sections(subject)
    subject_id = str(subject["_id"])

    if not sections:
        kb.add(InlineKeyboardButton("(no sections yet)", callback_data="noop"))
        return kb

    for idx, sec in enumerate(sections):
        item_count = section_item_count(sec)
        access = "FREE" if sec.get("is_free") or section_price(subject, sec) == 0 else f"₹{section_price(subject, sec)}"
        kb.add(InlineKeyboardButton(
            f"📂 {sec['name']} — {access} ({item_count} item{'s' if item_count != 1 else ''})",
            callback_data=f"{prefix}:{subject_id}:{idx}",
        ))
    return kb


def upload_done_keyboard(subject_id: str, section_idx: int, saved_count: int) -> InlineKeyboardMarkup:
    """Single-button keyboard shown after each file upload."""
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        f"✅ Done  ({saved_count} file{'s' if saved_count != 1 else ''} saved)",
        callback_data=f"upload_done:{subject_id}:{section_idx}",
    ))
    return kb


def upload_done_text_keyboard(subject_id: str, section_idx: int, saved_count: int) -> InlineKeyboardMarkup:
    """Single-button keyboard shown after each text note is saved."""
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        f"✅ Done  ({saved_count} note{'s' if saved_count != 1 else ''} saved)",
        callback_data=f"upload_done_text:{subject_id}:{section_idx}",
    ))
    return kb


# ---------------------------------------------------------------------------
# User keyboards
# ---------------------------------------------------------------------------

def contact_keyboard() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    kb.add(KeyboardButton("📱 Share Contact to Register", request_contact=True))
    return kb


def user_subjects_keyboard() -> InlineKeyboardMarkup:
    """Subject list for the /start browse flow."""
    kb = subjects_keyboard("buy")
    kb.add(InlineKeyboardButton("📂 View Purchased Notes", callback_data="view_purchased"))
    return kb


def purchased_subjects_keyboard(orders: list[dict]) -> InlineKeyboardMarkup:
    """List purchased subjects, each linking to its section picker."""
    from db.queries import fetch_subject

    kb = InlineKeyboardMarkup(row_width=1)
    seen: set[str] = set()
    for order in orders:
        if order["subject_id"] in seen:
            continue
        seen.add(order["subject_id"])
        sub = fetch_subject(order["subject_id"])
        if sub:
            sections  = get_sections(sub)
            sec_count = len(sections)
            kb.add(InlineKeyboardButton(
                f"📚 {sub['name']}  ({sec_count} section{'s' if sec_count != 1 else ''})",
                callback_data=f"view_sections:{str(sub['_id'])}",
            ))
    return kb


def view_sections_keyboard(subject: dict, orders: list[dict] | None = None) -> InlineKeyboardMarkup:
    """Section picker shown after a user selects a purchased subject."""
    subject_id = str(subject["_id"])
    sections   = get_sections(subject)
    kb         = InlineKeyboardMarkup(row_width=1)
    orders     = orders or []
    for idx, sec in enumerate(sections):
        item_count = section_item_count(sec)
        if has_section_access(orders, subject_id, idx, subject, sec):
            label = f"📂 {sec['name']} — Unlocked ({item_count} item{'s' if item_count != 1 else ''})"
            callback_data = f"download_section:{subject_id}:{idx}"
        else:
            price = section_price(subject, sec)
            label = f"🔒 {sec['name']} — ₹{price} ({item_count} item{'s' if item_count != 1 else ''})"
            callback_data = f"buy_section:{subject_id}:{idx}"
        kb.add(InlineKeyboardButton(
            label,
            callback_data=callback_data,
        ))
    return kb
