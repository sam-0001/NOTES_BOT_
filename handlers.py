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
from leaderboard import get_leaderboard_text

# Conversation states
CHOOSING_STAT = 0
STATS_AWAITING_YEAR = 1
AWAIT_FEEDBACK_BUTTON, AWAIT_FEEDBACK_TEXT = range(2)
CHOOSING_BROADCAST_TARGET, AWAITING_YEAR, AWAITING_BRANCH, AWAITING_MESSAGE = range(4)


# --- User Onboarding Conversation ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Greets owners and starts the setup for normal users with an intro."""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    if user_id in config.OWNER_IDS:
        await update.message.reply_text(
            f"👋 Welcome back, Admin {user_name}!\n\n"
            "You have access to all admin commands. Use /help to see the list."
        )
        return ConversationHandler.END
    if check_user_setup(context.user_data):
        await update.message.reply_text(
            f"👋 Welcome back, {context.user_data['name']}!\n\n"
            "Use /notes or /assignments. To see all commands, type /help."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        f"👋 Welcome to the SAOE Notes Bot, {user_name}!\n\n"
        "I'm here to help you get academic notes, assignments, and official notices quickly.\n\n"
        "To get started, let's set up your profile."
    )
    reply_keyboard = [["1st Year", "2nd Year"], ["3rd Year", "4th Year"]]
    await update.message.reply_text(
        "Please select your academic year:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return config.ASK_YEAR

async def received_year(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['year'] = update.message.text
    # Add a timestamp for new user analytics
    context.user_data['created_at'] = datetime.utcnow()
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

# --- Standard User Commands ---
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
            "📊 */stats* - View bot usage analytics.\n"
            "📡 */broadcast* - Send a message to users.\n"
            "🗂️ */getnotes* `<Y> <B> <S>` - Direct file access.\n"
            "📋 */getassignments* `<Y> <B> <S>` - Direct file access."
        )
        help_text += admin_text
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    context.user_data.clear()
    db = context.application.persistence.db
    db["user_data"].delete_one({"_id": user_id})
    await update.message.reply_text(
        f"Okay {user_name}, I've completely cleared your data. "
        "Please use /start to set up your profile again."
    )

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

@rate_limit(limit_seconds=10, max_calls=1)
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🏆 Fetching the leaderboard...")
    leaderboard_text = get_leaderboard_text(context)
    await update.message.reply_text(leaderboard_text, parse_mode="Markdown")

# --- In-App Feedback Conversation ---
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
    await query.edit_message_text("Great! Please type your suggestion, feedback, or bug report and send it to me now. Type /cancel to quit.")
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

# --- Core File & Notice Functionality ---
@rate_limit(limit_seconds=10, max_calls=2)
@busy_lock
async def file_selection_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if not check_user_setup(context.user_data):
            await update.message.reply_text("Please run /start first to set up your profile.")
            return
        greeting = f"{random.choice(config.GREETINGS)}, {context.user_data['name']}!"
        await update.message.reply_text(greeting)
        service = get_drive_service()
        if not service:
            await update.message.reply_text("Could not connect to Google Drive at the moment. Please try again later.")
            return
        command_type = 'notes' if update.message.text.startswith('/notes') else 'assignments'
        year_folder_name = context.user_data['year'].replace(" ", "_")
        branch_name = context.user_data['branch']
        year_id = get_folder_id(service, config.GOOGLE_DRIVE_ROOT_FOLDER_ID, year_folder_name)
        if not year_id:
            await update.message.reply_text("Could not find your year folder on Drive.")
            return
        branch_id = get_folder_id(service, year_id, branch_name)
        if not branch_id:
            await update.message.reply_text("Could not find your branch folder on Drive.")
            return
        subjects = list_items(service, branch_id, "folders")
        valid_subjects = [s for s in subjects if s.get("name")]
        if not valid_subjects:
            await update.message.reply_text("No subjects found for your branch.")
            return
        subject_names_map = {s['id']: s['name'] for s in valid_subjects}
        context.user_data['last_subject_names'] = subject_names_map
        keyboard = [
            [InlineKeyboardButton(s['name'], callback_data=f"subj:{s['id']}:{command_type}")]
            for s in valid_subjects
        ]
        await update.message.reply_text(
            f"Please select a subject to get {command_type}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        config.logger.error(f"Error in file_selection_command: {e}")
        await update.message.reply_text("❗️ An error occurred. Please try again later.")

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
            orderBy="createdTime desc", pageSize=1, fields="files(name, webViewLink)",
            supportsAllDrives=True, includeItemsFromAllDrives=True
        ).execute().get('files', [])
        if not files:
            await update.message.reply_text("There are no notices at the moment.")
            return
        message = f"📢 *Latest Notice*\n\n📄 **File:** `{files[0].get('name')}`"
        keyboard = [[InlineKeyboardButton("Download Notice", url=files[0].get('webViewLink'))]]
        await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        config.logger.error(f"Error in get_notice_command: {e}")
        await update.message.reply_text("❗️ Drive is temporarily unavailable for notices. Please try again later.")

# --- Admin Commands ---
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
        reply_keyboard = [["1st Year", "2nd Year"], ["3rd Year", "4th Year"]]
        await query.message.reply_text(
            "Please select a year to see its trending subjects.",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
        )
        await query.delete_message()
        return STATS_AWAITING_YEAR
    elif query.data == "stats_export_users":
        await query.edit_message_text("Generating user report, please wait...")
        user_docs = list(db["user_data"].find({}))
        user_list = [doc.get('data', {}) for doc in user_docs]
        if not user_list:
            await query.edit_message_text("No user data to export.")
            return ConversationHandler.END
        df = pd.DataFrame(user_list)
        if 'points' not in df.columns:
            df['points'] = 0
        df['points'] = df['points'].fillna(0).astype(int)
        df_filtered = df[['name', 'year', 'branch', 'points']]
        output = io.BytesIO()
        df_filtered.to_excel(output, index=False, sheet_name='Users', engine='openpyxl')
        output.seek(0)
        await context.bot.send_document(chat_id=query.from_user.id, document=output, filename="Filtered_Users_Report.xlsx")
        await query.delete_message()
        return ConversationHandler.END

async def stats_receive_year(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selected_year = update.message.text
    await update.message.reply_text(f"Gathering stats for {selected_year}, please wait...", reply_markup=ReplyKeyboardRemove())
    db = context.application.persistence.db
    year_users = list(db["user_data"].find({"data.year": selected_year}, {"_id": 1}))
    user_ids_in_year = [user["_id"] for user in year_users]
    pipeline = [
        {"$match": {"user_id": {"$in": user_ids_in_year}}},
        {"$group": {"_id": "$subject_name", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]
    trending_subjects = list(db["access_logs"].aggregate(pipeline))
    stats_text = f"📊 *Analytics for {selected_year}*\n\n"
    stats_text += f"👥 *Total Registered Users in this year:* {len(user_ids_in_year)}\n\n"
    stats_text += "📈 *Trending Subjects (by clicks):*\n"
    if trending_subjects:
        for i, subject in enumerate(trending_subjects):
            stats_text += f"{i+1}. {subject['_id']} ({subject['count']} clicks)\n"
    else:
        stats_text += "No subject usage has been recorded for this year yet."
    await update.message.reply_text(stats_text, parse_mode="Markdown")
    return ConversationHandler.END

@owner_only
async def admin_get_files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_notes = update.message.text.startswith("/getnotes")
    command_type = "notes" if is_notes else "assignments"
    command_name = "/getnotes" if is_notes else "/getassignments"
    args = context.args
    if len(args) == 0:
        await update.message.reply_text(
            f"Please provide arguments.\n\nUsage:\n`{command_name} <Year> <Branch> [Subject]`\n\n"
            "Example:\n`/getnotes 2nd_Year Computer DSA`",
            parse_mode="Markdown"
        )
        return
    service = get_drive_service()
    if not service:
        await update.message.reply_text("Could not connect to Google Drive.")
        return
    try:
        year_name = args[0]
        year_id = get_folder_id(service, config.GOOGLE_DRIVE_ROOT_FOLDER_ID, year_name)
        if not year_id:
            await update.message.reply_text(f"Year '{year_name}' not found.")
            return
        if len(args) == 1:
            branches = list_items(service, year_id, "folders")
            branch_names = "\n".join([f"- `{b['name']}`" for b in branches])
            await update.message.reply_text(f"Branches in {year_name}:\n{branch_names}", parse_mode="Markdown")
            return
        branch_name = args[1]
        branch_id = get_folder_id(service, year_id, branch_name)
        if not branch_id:
            await update.message.reply_text(f"Branch '{branch_name}' not found in '{year_name}'.")
            return
        if len(args) == 2:
            subjects = list_items(service, branch_id, "folders")
            subject_names = "\n".join([f"- `{s['name']}`" for s in subjects])
            await update.message.reply_text(f"Subjects in {year_name}, {branch_name}:\n{subject_names}", parse_mode="Markdown")
            return
        subject_name = args[2]
        subject_id = get_folder_id(service, branch_id, subject_name)
        if not subject_id:
            await update.message.reply_text(f"Subject '{subject_name}' not found.")
            return
        subfolder_name = "Notes" if is_notes else "Assignments"
        target_folder_id = get_folder_id(service, subject_id, subfolder_name)
        if not target_folder_id:
            await update.message.reply_text(f"The '{subfolder_name}' folder for '{subject_name}' doesn't exist.")
            return
        files = list_items(service, target_folder_id, "files")
        if not files:
            await update.message.reply_text(f"No {command_type} found for '{subject_name}'.")
            return
        await update.message.reply_text(f"Found {len(files)} {command_type} for '{subject_name}'. Sending them now...")
        for file_item in files:
            file_content = download_file(service, file_item['id'])
            if file_content:
                await update.message.reply_document(document=file_content, filename=file_item['name'])
            await asyncio.sleep(1)
    except Exception as e:
        config.logger.error(f"Error in admin_get_files_command: {e}")
        await update.message.reply_text("An error occurred. Please check your arguments and try again.")

@owner_only
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("📣 All Users", callback_data="broadcast_all")], [InlineKeyboardButton("🎯 Specific Group", callback_data="broadcast_specific")]]
    await update.message.reply_text("Who should receive this broadcast message?", reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_BROADCAST_TARGET

async def broadcast_target_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    target = query.data
    if target == "broadcast_all":
        context.user_data['broadcast_target'] = {"all": True}
        await query.edit_message_text("Please send the message you want to broadcast to all users. Type /cancel to quit.")
        return AWAITING_MESSAGE
    elif target == "broadcast_specific":
        context.user_data['broadcast_target'] = {}
        reply_keyboard = [["1st Year", "2nd Year"], ["3rd Year", "4th Year"]]
        await query.message.reply_text("Please select the target year.", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))
        await query.delete_message()
        return AWAITING_YEAR

async def broadcast_year_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    year = update.message.text
    context.user_data['broadcast_target']['year'] = year
    service = get_drive_service()
    year_folder_name = year.replace(" ", "_")
    year_folder_id = get_folder_id(service, config.GOOGLE_DRIVE_ROOT_FOLDER_ID, year_folder_name)
    branches = list_items(service, year_folder_id, "folders")
    branch_names = [b['name'] for b in branches]
    reply_keyboard = [branch_names[i:i + 2] for i in range(0, len(branch_names), 2)]
    await update.message.reply_text("Now, please select the target branch.", reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))
    return AWAITING_BRANCH

async def broadcast_branch_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    branch = update.message.text
    context.user_data['broadcast_target']['branch'] = branch
    await update.message.reply_text(
        f"Target set to: {context.user_data['broadcast_target']['year']}, {branch}.\n\n"
        "Now, please send the message to broadcast (text, image with caption, or document with caption).",
        reply_markup=ReplyKeyboardRemove()
    )
    return AWAITING_MESSAGE

async def broadcast_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    target_criteria = context.user_data.get('broadcast_target', {})
    message = update.message
    await update.message.reply_text("Finding users and preparing to broadcast...")
    query_filter = {}
    if not target_criteria.get("all", False):
        query_filter["data.year"] = target_criteria.get("year")
        query_filter["data.branch"] = target_criteria.get("branch")
    db = context.application.persistence.db
    target_users = list(db["user_data"].find(query_filter, {"_id": 1}))
    user_ids = [user["_id"] for user in target_users]
    if not user_ids:
        await update.message.reply_text("No users found matching the criteria. Broadcast cancelled.")
        return ConversationHandler.END
    await update.message.reply_text(f"Found {len(user_ids)} users. Starting broadcast... This may take some time.")
    success_count = 0
    fail_count = 0
    for user_id in user_ids:
        try:
            await message.forward(chat_id=user_id)
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            fail_count += 1
            config.logger.error(f"Failed to send broadcast to {user_id}: {e}")
    await update.message.reply_text(
        f"Broadcast complete!\n\n✅ Sent successfully to {success_count} users.\n"
        f"❌ Failed to send to {fail_count} users (they may have blocked the bot)."
    )
    if 'broadcast_target' in context.user_data:
        del context.user_data['broadcast_target']
    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'broadcast_target' in context.user_data:
        del context.user_data['broadcast_target']
    await update.message.reply_text("Broadcast cancelled.")
    return ConversationHandler.END

# --- General Callback Query Handler ---
@busy_lock
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data.startswith("stats_"):
        return
        
    data_parts = query.data.split(":")
    action = data_parts[0]
    
    if action == 'subj':
        subject_id = data_parts[1]
        command_type = data_parts[2]
        subject_name = context.user_data.get('last_subject_names', {}).get(subject_id)
        if not subject_name:
            await query.edit_message_text("Sorry, something went wrong. Please try the command again.")
            return
            
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
        
        file_names_map = {f['id']: f['name'] for f in files}
        context.user_data['last_file_names'] = file_names_map
        keyboard = [
            [InlineKeyboardButton(f['name'], callback_data=f"dl:{f['id']}")]
            for f in files
        ]
        await query.edit_message_text(
            text=f"Select a file from '{subject_name}':", reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif action == 'dl':
        # Award points for the download
        context.application.persistence.db["user_data"].update_one(
            {"_id": query.from_user.id}, 
            {"$inc": {"data.points": 1}}, 
            upsert=True
        )
        
        file_id = data_parts[1]
        file_name = context.user_data.get('last_file_names', {}).get(file_id)
        if not file_name:
            await query.edit_message_text("Sorry, something went wrong. Please try again.")
            return
            
        await query.edit_message_text(text=f"⬇️ Preparing to download '{file_name}'...")
        wait_task = asyncio.create_task(send_wait_message(context, query.message.chat.id))
        try:
            service = get_drive_service()
            file_content = download_file(service, file_id) if service else None
        finally:
            wait_task.cancel()
        if file_content:
            await context.bot.send_document(chat_id=query.message.chat.id, document=file_content, filename=file_name)
            try: await query.delete_message()
            except Exception: pass
        else:
            await query.edit_message_text(f"❌ Sorry, failed to download '{file_name}'.")
