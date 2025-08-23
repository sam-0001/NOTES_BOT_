# handlers.py

import io
import random
import asyncio
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
)

# Local imports
import config
from drive_utils import get_drive_service, get_folder_id, list_items, download_file, upload_file
from bot_helpers import owner_only, busy_lock, check_user_setup, send_wait_message

# Conversation states
AWAIT_NOTICE_FILE = 0

# --- Conversation Handlers (for /start setup) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation and asks for the user's year."""
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
    """Stores the year and asks for the branch."""
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
    """Stores the branch and asks for the name."""
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
    """Stores the name and ends the conversation."""
    context.user_data['name'] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Thanks, {context.user_data['name']}! Your setup is complete.\n\nType /help to see all commands."
    )
    if 'available_branches' in context.user_data:
        del context.user_data['available_branches']
    return ConversationHandler.END


# --- Standard Command Handlers ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a dynamic help message based on user permissions."""
    user_id = update.effective_user.id
    
    help_text = (
        "Here are the available commands:\n\n"
        "🚀 */start* - Set up your profile.\n"
        "📢 */notice* - View the latest notice.\n"
        "📖 */notes* - Get notes for a subject.\n"
        "✍️ */assignments* - Get assignments for a subject.\n"
        "💡 */suggest* - Share your feedback or ideas.\n"
        "👤 */myinfo* - Check your current settings.\n"
        "🔄 */reset* - Clear your data and start over.\n"
        "❓ */help* - Show this help message."
    )
    
    if user_id in config.OWNER_IDS:
        admin_text = (
            "\n\n*Admin Commands:*\n"
            "🤫 */postnotice* - Post a new notice."
        )
        help_text += admin_text

    await update.message.reply_text(help_text, parse_mode="Markdown")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clears user data and restarts the setup."""
    user_name = context.user_data.get('name', 'there')
    context.user_data.clear()
    await update.message.reply_text(f"Okay {user_name}, I've cleared your data. Please use /start to set up again.")


async def myinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the user's current settings."""
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


async def suggestion_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message with a link to the suggestions Google Form."""
    suggestion_text = (
        "Thank you for using our bot! We are always looking to improve and "
        "your feedback is invaluable to us. 😊\n\n"
        "Please share your thoughts, ideas, or any issues you've faced. We read every suggestion!"
    )
    keyboard = [[
        InlineKeyboardButton(
            text="✍️ Give a Suggestion",
            url="https://forms.gle/TpNB1mD15To6bhQn8"
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(suggestion_text, reply_markup=reply_markup)


@busy_lock
async def file_selection_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /notes and /assignments commands by showing a subject list."""
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
        f"Please select a subject to get {command_type}:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@busy_lock
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles all inline button presses."""
    query = update.callback_query
    await query.answer()
    data_parts = query.data.split(":", 3)
    action = data_parts[0]

    service = get_drive_service()
    if not service:
        await query.edit_message_text("Could not connect to Google Drive right now.")
        return

    if action == 'subj':
        subject_id, subject_name, command_type = data_parts[1], data_parts[2], data_parts[3]
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
            text=f"Select a file from '{subject_name}':",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif action == 'dl':
        file_id, file_name = data_parts[1], data_parts[2]
        await query.edit_message_text(text=f"⬇️ Preparing to download '{file_name}'...")

        wait_task = asyncio.create_task(send_wait_message(context, query.message.chat.id))
        try:
            file_content = download_file(service, file_id)
        finally:
            wait_task.cancel()

        if file_content:
            await context.bot.send_document(
                chat_id=query.message.chat.id,
                document=file_content,
                filename=file_name
            )
            try:
                await query.delete_message()
            except Exception:
                pass
        else:
            await query.edit_message_text(text=f"❌ Sorry, failed to download '{file_name}'.")


# --- Owner & Notice Commands ---

@owner_only
async def post_notice_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the notice posting process for owners."""
    await update.message.reply_text("Please send the file you want to post as a notice. To cancel, type /cancel.")
    return AWAIT_NOTICE_FILE

async def receive_notice_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the file, uploads it, and saves it as the current notice."""
    doc = update.message.document
    if not doc:
        await update.message.reply_text("That's not a file. Please send a document or type /cancel.")
        return AWAIT_NOTICE_FILE

    await update.message.reply_text("Got it. Uploading to Google Drive...")
    
    file_handle = io.BytesIO()
    file_obj = await doc.get_file()
    await file_obj.download_to_memory(file_handle)
    file_handle.seek(0)

    service = get_drive_service()
    data_folder_id = get_folder_id(service, config.GOOGLE_DRIVE_ROOT_FOLDER_ID, "DATA")
    if not data_folder_id:
        await update.message.reply_text("❌ Error: The 'DATA' folder was not found in Google Drive.")
        return ConversationHandler.END

    uploaded_file = upload_file(service, data_folder_id, doc.file_name, file_handle, doc.mime_type)

    if not uploaded_file:
        await update.message.reply_text("❌ Sorry, there was an error uploading the file.")
        return ConversationHandler.END

    notice_data = {
        "file_name": doc.file_name,
        "file_link": uploaded_file.get('webViewLink'),
        "timestamp": update.message.date
    }
    
    context.application.persistence.db["notices"].update_one(
        {"_id": "latest_notice"}, {"$set": notice_data}, upsert=True
    )
    
    await update.message.reply_text("✅ Notice has been successfully posted!")
    return ConversationHandler.END

async def cancel_notice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the notice posting process."""
    await update.message.reply_text("Notice posting cancelled.")
    return ConversationHandler.END

async def get_notice_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allows any user to view the latest notice."""
    notice_doc = context.application.persistence.db["notices"].find_one({"_id": "latest_notice"})
    
    if not notice_doc:
        await update.message.reply_text("There are no notices at the moment.")
        return

    file_name = notice_doc.get("file_name")
    file_link = notice_doc.get("file_link")
    timestamp = notice_doc.get("timestamp").strftime("%d %b %Y, %I:%M %p")
    
    message = (
        f"📢 *Latest Notice*\n\n"
        f"📄 **File:** `{file_name}`\n"
        f"🗓️ **Posted on:** {timestamp}"
    )
    keyboard = [[InlineKeyboardButton("Download Notice", url=file_link)]]
    
    await update.message.reply_text(
        message, 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode="Markdown"
    )
