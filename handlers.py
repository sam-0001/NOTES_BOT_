# handlers.py

import io
import random
import asyncio
import pandas as pd
from datetime import datetime
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

# Local imports
import config
from drive_utils import get_drive_service, get_folder_id, list_items, download_file
from bot_helpers import owner_only, busy_lock, check_user_setup, send_wait_message, rate_limit

# Conversation states
CHOOSING_STAT = 0
AWAIT_FEEDBACK_BUTTON, AWAIT_FEEDBACK_TEXT = range(2)

# --- Conversation Handlers (/start) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    if user_id in config.OWNER_IDS:
        await update.message.reply_text(
            f"👋 Welcome back, Admin {user_name}!\n\n"
            "You have access to all commands. Use /stats to see analytics."
        )
        return ConversationHandler.END
    if check_user_setup(context.user_data):
        await update.message.reply_text(
            f"👋 Welcome back, {context.user_data['name']}!\n\n"
            "Use /notes or /assignments. To change your details, use /reset first."
        )
        return ConversationHandler.END
    reply_keyboard = [["1st Year", "2nd Year"], ["3rd Year", "4th Year"]]
    await update.message.reply_text(
        "👋 Welcome! Let's get you set up.\nFirst, please select your academic year.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return config.ASK_YEAR

async def received_year(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['year'] = update.message.text
    year_folder_name = context.user_data['year'].replace(" ", "_")
    await update.message.reply_text("Got it. Fetching available branches...", reply_markup=ReplyKeyboardRemove())
    service = get_drive_service()
    if not service:
        await update.message.reply_text("Could not connect to Google Drive. Please /start again.")
        return ConversationHandler.END
    year_folder_id = get_folder_id(service, config.GOOGLE_DRIVE_ROOT_FOLDER_ID, year_folder_name)
    if not year_folder_id:
        await update.message.reply_text(f"Could not find folder for '{context.user_data['year']}'. Please /start again.")
        return ConversationHandler.END
    branches = list_items(service, year_folder_id, "folders")
    if not branches:
        await update.message.reply_text("No branches found for your year. Please /start again.")
        return ConversationHandler.END
    branch_names = [b['name'] for b in branches]
    reply_keyboard = [branch_names[i:i + 2] for i in range(0, len(branch_names), 2)]
    await update.message.reply_text(
        "Now, please select your branch.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    context.user_data['available_branches'] = branch_names
    return config.ASK_BRANCH

async def received_branch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_branch = update.message.text
    if user_branch not in context.user_data.get('available_branches', []):
        await update.message.reply_text("Invalid branch. Please select one from the keyboard.")
        return config.ASK_BRANCH
    context.user_data['branch'] = user_branch
    await update.message.reply_text(
        f"Great, you're in {context.user_data['year']}, {user_branch}.\n\nFinally, what's your name?",
        reply_markup=ReplyKeyboardRemove(),
    )
    return config.ASK_NAME

async def received_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['name'] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Thanks, {context.user_data['name']}! Your setup is complete.\n\nType /help to see all commands."
    )
    if 'available_branches' in context.user_data:
        del context.user_data['available_branches']
    return ConversationHandler.END

# --- Standard Command Handlers ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    help_text = (
        "Here are the available commands:\n\n"
        "🚀 */start* - Set up your profile.\n"
        "📢 */notice* - View the latest notice.\n"
        "📖 */notes* - Get notes for a subject.\n"
        "✍️ */assignments* - Get assignments for a subject.\n"
        "💡 */suggest* - Share your feedback or ideas.\n"
        "🏆 */leaderboard* - See the top study champions.\n"
        "👤 */myinfo* - Check your current settings.\n"
        "🔄 */reset* - Clear your data and start over.\n"
        "❓ */help* - Show this help message."
    )
    if user_id in config.OWNER_IDS:
        admin_text = (
            "\n\n*Admin Commands:*\n"
            "📊 */stats* - View bot usage analytics."
        )
        help_text += admin_text
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = context.user_data.get('name', 'there')
    context.user_data.clear()
    await update.message.reply_text(f"Okay {user_name}, I've cleared your data. Please use /start to set up again.")

async def myinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if check_user_setup(context.user_data):
        greeting = f"{random.choice(config.GREETINGS)}, {context.user_data['name']}!"
        text = (
            f"{greeting}\n\nYour current settings are:\n"
            f"- *Year:* {context.user_data['year']}\n"
            f"- *Branch:* {context.user_data['branch']}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text("You haven't completed the setup yet! Please run /start.")

# --- Suggestion Conversation Handler ---
async def suggestion_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("✍️ Leave Feedback", callback_data="leave_feedback")]]
    await update.message.reply_text(
        "We'd love to hear your thoughts! Click the button below to leave your feedback.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return AWAIT_FEEDBACK_BUTTON

async def prompt_for_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Great! Please type your suggestion, feedback, or bug report and send it to me now.")
    return AWAIT_FEEDBACK_TEXT

async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    feedback_text = update.message.text
    user = update.effective_user
    await update.message.reply_text("✅ Thank you! Your feedback has been sent to the admin team.")
    if config.FEEDBACK_GROUP_ID:
        forward_message = (
            f"📬 *New Feedback Received*\n\n"
            f"👤 *From:* {user.first_name} (@{user.username}, ID: `{user.id}`)\n\n"
            f"```{feedback_text}```"
        )
        await context.bot.send_message(
            chat_id=config.FEEDBACK_GROUP_ID, text=forward_message, parse_mode="Markdown"
        )
    return ConversationHandler.END

async def cancel_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Feedback process cancelled.")
    return ConversationHandler.END

# --- Core Bot Functionality ---
@rate_limit(limit_seconds=10, max_calls=2)
@busy_lock
async def file_selection_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if not check_user_setup(context.user_data):
            await update.message.reply_text("Please run /start first to set up your profile.")
            return
        greeting = f"{random.choice(config.GREETINGS)}, {context.user_data['name']}!"
        await update.message.reply_text(greeting)
        command_type = 'notes' if update.message.text.startswith('/notes') else 'assignments'
        year_folder_name = context.user_data['year'].replace(" ", "_")
        branch_name = context.user_data['branch']
        service = get_drive_service()
        if not service:
            await update.message.reply_text("Could not connect to Google Drive right now.")
            return
        year_id = get_folder_id(service, config.GOOGLE_DRIVE_ROOT_FOLDER_ID, year_folder_name)
        if not year_id:
            await update.message.reply_text("Could not find your year folder on Drive.")
            return
        branch_id = get_folder_id(service, year_id, branch_name)
        if not branch_id:
            await update.message.reply_text("Could not find your branch folder on Drive.")
            return
        subjects = list_items(service, branch_id, "folders")
        if not subjects:
            await update.message.reply_text("No subjects found for your branch.")
            return
        keyboard = [
            [InlineKeyboardButton(s['name'], callback_data=f"subj:{s['id']}:{s['name']}:{command_type}")]
            for s in subjects
        ]
        await update.message.reply_text(
            f"Please select a subject to get {command_type}:", reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        config.logger.error(f"Error in file_selection_command: {e}")
        await update.message.reply_text("❗️ An error occurred while communicating with Google Drive. Please try again later.")

@rate_limit(limit_seconds=5, max_calls=1)
async def get_notice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await update.message.reply_text("Checking for the latest notice, please wait...")
        service = get_drive_service()
        if not service:
            await update.message.reply_text("Could not connect to Google Drive.")
            return
        data_folder_id = get_folder_id(service, config.SHARED_DRIVE_ID, "DATA")
        if not data_folder_id:
            await update.message.reply_text("The 'DATA' folder for notices could not be found.")
            return
        files = service.files().list(
            q=f"'{data_folder_id}' in parents and trashed = false",
            orderBy="createdTime desc",
            pageSize=1,
            fields="files(name, webViewLink, createdTime)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute().get('files', [])
        if not files:
            await update.message.reply_text("There are no notices at the moment.")
            return
        latest_notice = files[0]
        file_name = latest_notice.get("name")
        file_link = latest_notice.get("webViewLink")
        message = f"📢 *Latest Notice*\n\n📄 **File:** `{file_name}`"
        keyboard = [[InlineKeyboardButton("Download Notice", url=file_link)]]
        await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        config.logger.error(f"Error in get_notice_command: {e}")
        await update.message.reply_text("❗️ Drive is temporarily unavailable for notices. Please try again later.")

@rate_limit(limit_seconds=10, max_calls=1)
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🏆 Fetching the leaderboard...")
    db = context.application.persistence.db
    pipeline = [
        {"$match": {"data.points": {"$exists": True}}},
        {"$sort": {"data.points": -1}},
        {"$limit": 10}
    ]
    top_users = list(db["user_data"].aggregate(pipeline))
    if not top_users:
        await update.message.reply_text("The leaderboard is empty. Start downloading files to get points!")
        return
    leaderboard_text = "🏆 *Top 10 Study Champions*\n\n"
    rank_emojis = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    for i, user_doc in enumerate(top_users):
        user_data = user_doc.get("data", {})
        name = user_data.get("name", "A User")
        points = user_data.get("points", 0)
        leaderboard_text += f"{rank_emojis[i]} *{name}* - {points} points\n"
    await update.message.reply_text(leaderboard_text, parse_mode="Markdown")

# --- Admin Stats Command ---
@owner_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("📊 Quick Stats", callback_data="stats_quick")],
        [InlineKeyboardButton("📄 Export All Users to Excel", callback_data="stats_export_users")],
    ]
    await update.message.reply_text("Admin Analytics Dashboard\n\nPlease choose an option:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_STAT

async def stats_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    db = context.application.persistence.db
    if query.data == "stats_quick":
        await query.edit_message_text("Gathering stats, please wait...")
        total_users = db["user_data"].count_documents({})
        pipeline = [
            {"$group": {"_id": "$subject_name", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5}
        ]
        trending_subjects = list(db["access_logs"].aggregate(pipeline))
        stats_text = f"📊 *Quick Bot Analytics*\n\n👥 *Total Registered Users:* {total_users}\n\n📈 *Trending Subjects (by clicks):*\n"
        if trending_subjects:
            for i, subject in enumerate(trending_subjects):
                stats_text += f"{i+1}. {subject['_id']} ({subject['count']} clicks)\n"
        else:
            stats_text += "No subject usage has been recorded yet."
        await query.edit_message_text(stats_text, parse_mode="Markdown")
    elif query.data == "stats_export_users":
        await query.edit_message_text("Generating user report, please wait...")
        user_docs = list(db["user_data"].find({}))
        user_list = [doc.get('data', {}) for doc in user_docs]
        if not user_list:
            await query.edit_message_text("No user data to export.")
            return ConversationHandler.END
        df = pd.DataFrame(user_list)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Users')
        output.seek(0)
        await context.bot.send_document(
            chat_id=query.from_user.id, document=output, filename="All_Users_Report.xlsx"
        )
        await query.delete_message()
    return ConversationHandler.END

# --- General Callback Query Handler ---
@busy_lock
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data.startswith("stats_"):
        return
    data_parts = query.data.split(":", 3)
    action = data_parts[0]
    if action == 'subj':
        subject_id, subject_name, command_type = data_parts[1], data_parts[2], data_parts[3]
        context.application.persistence.db["access_logs"].insert_one({
            "user_id": query.from_user.id,
            "subject_name": subject_name,
            "type": command_type,
            "timestamp": datetime.utcnow()
        })
        service = get_drive_service()
        if not service:
            await query.edit_message_text("Could not connect to Google Drive right now.")
            return
        subfolder_name = "Notes" if command_type == "notes" else "Assignments"
        target_folder_id = get_folder_id(service, subject_id, subfolder_name)
        if not target_folder_id:
            await query.edit_message_text(f"The '{subfolder_name}' folder for '{subject_name}' doesn't exist.")
            return
        files = list_items(service, target_folder_id, "files")
        if not files:
            await query.edit_message_text(f"No {command_type} found for '{subject_name}'.")
            return
        keyboard = [
            [InlineKeyboardButton(f['name'], callback_data=f"dl:{f['id']}:{f['name']}")]
            for f in files
        ]
        await query.edit_message_text(
            text=f"Select a file from '{subject_name}':", reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif action == 'dl':
        context.application.persistence.db["user_data"].update_one(
            {"_id": query.from_user.id}, {"$inc": {"data.points": 1}}, upsert=True
        )
        file_id, file_name = data_parts[1], data_parts[2]
        await query.edit_message_text(text=f"⬇️ Preparing to download '{file_name}'...")
        wait_task = asyncio.create_task(send_wait_message(context, query.message.chat.id))
        try:
            service = get_drive_service()
            if not service:
                await query.edit_message_text("Could not connect to Google Drive right now.")
                return
            file_content = download_file(service, file_id)
        finally:
            wait_task.cancel()
        if file_content:
            await context.bot.send_document(
                chat_id=query.message.chat.id, document=file_content, filename=file_name
            )
            try:
                await query.delete_message()
            except Exception:
                pass
        else:
            await query.edit_message_text(text=f"❌ Sorry, failed to download '{file_name}'.")
