"""
bot/handlers/commands.py
~~~~~~~~~~~~~~~~~~~~~~~~
Handlers for all bot slash-commands.
"""

import telebot
from telebot.types import ReplyKeyboardRemove

from bot.instance import bot
from bot.cleanup import send_tracked, sweep
from bot.keyboards import contact_keyboard, user_subjects_keyboard, purchased_subjects_keyboard
from bot.state import clear_state, pop_pending_referral, set_pending_referral
from config import ADMIN_ID
from db.queries import (
    fetch_all_subjects,
    fetch_user_by_chat,
    fetch_user_orders,
    fetch_subject,
    fetch_referral_count,
    fetch_reward_claims,
    get_settings,
    async_upsert_user,
    async_record_referral,
)
from db.client import run_async
from utils.sections import get_sections
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

def _promo_footer() -> str:
    """Return the admin-set persistent promo line, or '' if none is set."""
    try:
        promo = get_settings().get("promo_message", "")
    except Exception:
        promo = ""
    return f"\n\n📣 {promo}" if promo else ""


@bot.message_handler(commands=["start"])
def cmd_start(message: telebot.types.Message) -> None:
    cid = message.chat.id
    sweep(bot, cid)

    # ── Capture a referral code from a deep link: /start <referrer_chat_id> ──
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        ref_code = parts[1].strip()
        if ref_code and ref_code != str(cid):
            set_pending_referral(cid, ref_code)

    try:
        user = fetch_user_by_chat(str(cid))
    except Exception as exc:
        send_tracked(bot, cid, "⚠️ System is connecting. Please try again in 5 seconds.")
        return

    if not user:
        send_tracked(
            bot,
            cid,
            "👋 Welcome to *UNIEVAL*!\n\n"
            "To access study materials, please link your account.\n\n"
            "👇 *Tap the button below* to share your contact securely, "
            "OR simply type your 10-digit mobile number in the chat.",
            reply_markup=contact_keyboard(),
            parse_mode="Markdown",
        )
        return

    subs = fetch_all_subjects()
    kb   = user_subjects_keyboard()
    footer = _promo_footer()

    if not subs:
        send_tracked(
            bot,
            cid,
            f"👋 Welcome back to *UNIEVAL*!\n\nNo study materials are available yet.{footer}",
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    send_tracked(
        bot,
        cid,
        f"👋 Welcome back to *UNIEVAL*!\n\n📚 Choose a subject below to unlock its complete notes:{footer}",
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ---------------------------------------------------------------------------
# /get — quick re-browse without the welcome banner (fetch new notes anytime)
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["get"])
def cmd_get(message: telebot.types.Message) -> None:
    cid = message.chat.id
    sweep(bot, cid)

    user = fetch_user_by_chat(str(cid))
    if not user:
        # Not registered yet — same registration prompt as /start.
        cmd_start(message)
        return

    subs = fetch_all_subjects()
    kb   = user_subjects_keyboard()
    footer = _promo_footer()

    if not subs:
        send_tracked(bot, cid, f"📚 No study materials are available yet.{footer}",
                     parse_mode="Markdown", reply_markup=kb)
        return

    send_tracked(
        bot,
        cid,
        f"📚 *Browse subjects* — choose one below:{footer}",
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ---------------------------------------------------------------------------
# Contact share → register
# ---------------------------------------------------------------------------

@bot.message_handler(content_types=["contact"])
def handle_contact(message: telebot.types.Message) -> None:
    if message.contact is None:
        return
    mobile   = message.contact.phone_number
    chat_id  = str(message.chat.id)
    is_new   = run_async(async_upsert_user(chat_id, mobile))

    if is_new:
        ref_code = pop_pending_referral(message.chat.id)
        if ref_code:
            credited = run_async(async_record_referral(ref_code, chat_id))
            if credited:
                try:
                    bot.send_message(
                        int(ref_code),
                        "🎉 Someone just joined using your referral link!\n"
                        "Use /myrefs to check your progress.",
                    )
                except Exception:
                    pass

    bot.send_message(message.chat.id, "✅ Registration successful!", reply_markup=ReplyKeyboardRemove())
    cmd_start(message)


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["help"])
def cmd_help(message: telebot.types.Message) -> None:
    bot.send_message(
        message.chat.id,
        "🆘 *UNIEVAL Help Center*\n\n"
        "🔹 /start – Browse available study materials\n"
        "🔹 /get – Quickly re-browse / fetch new notes\n"
        "🔹 /my_notes – Access your purchased materials\n"
        "🔹 /myrefs – Your referral link & rewards\n"
        "🔹 /connect_owner – Contact support\n"
        "🔹 /help – Show this message",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /connect_owner
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["connect_owner", "connectowner"])
def cmd_connect_owner(message: telebot.types.Message) -> None:
    bot.send_message(
        message.chat.id,
        "📞 *Contact Support*\n\n"
        "Have any doubts or didn't get access after payment?\n"
        "Please message on WhatsApp: *7350484629*\n\n"
        "_(Include your Telegram ID and a payment screenshot for faster help.)_",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /my_notes
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["mynotes", "my_notes"])
def cmd_my_notes(message: telebot.types.Message) -> None:
    orders = fetch_user_orders(str(message.chat.id))
    if not orders:
        bot.send_message(
            message.chat.id,
            "❌ *You haven't unlocked any subjects yet.*\n\nUse /start to browse available study materials.",
            parse_mode="Markdown",
        )
        return

    kb = purchased_subjects_keyboard(orders)
    bot.send_message(
        message.chat.id,
        "📂 *Your Unlocked Study Materials:*\n\nSelect a subject to view its sections:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ---------------------------------------------------------------------------
# /admin
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["admin"])
def cmd_admin(message: telebot.types.Message) -> None:
    from bot.keyboards import admin_main_keyboard

    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.send_message(
            message.chat.id,
            f"⛔ Access denied.\n\nYour Telegram ID is: `{user_id}`\n\n"
            f"If you are the admin, set `ADMIN_ID={user_id}` in your `.env` and restart.",
            parse_mode="Markdown",
        )
        return

    clear_state(message.chat.id)
    sweep(bot, message.chat.id)
    send_tracked(
        bot,
        message.chat.id,
        "🛠 *Admin Panel – UNIEVAL*\n\nWhat would you like to do?",
        parse_mode="Markdown",
        reply_markup=admin_main_keyboard(),
    )


# ---------------------------------------------------------------------------
# /myid
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["myid"])
def cmd_myid(message: telebot.types.Message) -> None:
    bot.send_message(
        message.chat.id,
        f"Your Telegram ID is: `{message.from_user.id}`",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /myrefs — referral link, progress, and reward claiming
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["myrefs", "referral", "invite"])
def cmd_myrefs(message: telebot.types.Message) -> None:
    from bot.keyboards import claim_reward_keyboard

    cid  = message.chat.id
    sweep(bot, cid)

    if not fetch_user_by_chat(str(cid)):
        send_tracked(
            bot, cid,
            "You need to register first — use /start and share your contact.",
        )
        return

    me       = bot.get_me()
    link     = f"https://t.me/{me.username}?start={cid}"
    count    = fetch_referral_count(str(cid))
    claims   = fetch_reward_claims(str(cid))
    threshold = get_settings().get("referral_threshold", 5)
    available = max(0, (count // threshold) - claims)
    progress  = count % threshold

    text = (
        "🎁 *Refer & Earn Free Notes!*\n\n"
        f"👥 Invite friends with your link — once *{threshold}* friends register, "
        "you unlock one subject's notes for free.\n\n"
        f"🔗 Your link:\n`{link}`\n\n"
        f"✅ Total friends joined: *{count}*\n"
        f"📊 Progress to next reward: *{progress}/{threshold}*\n"
        f"🎉 Free unlocks available to claim: *{available}*"
    )

    kb = claim_reward_keyboard() if available > 0 else None
    send_tracked(bot, cid, text, parse_mode="Markdown", reply_markup=kb)
