import os
import logging
import re
import io
import json
import asyncio

# Third-party libraries
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.error import TimedOut, TelegramError

# Google Drive Imports
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

# Webhook-related imports for deployment
from flask import Flask, request
from asgiref.wsgi import WsgiToAsgi

# --- Configuration and Setup ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_DRIVE_ROOT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID")
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")

# Check for essential environment variables
if not all([TELEGRAM_BOT_TOKEN, GOOGLE_DRIVE_ROOT_FOLDER_ID, SERVICE_ACCOUNT_JSON]):
    raise ValueError("One or more required environment variables are missing.")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- State definitions for ConversationHandler ---
SELECT_YEAR, GET_NAME, MAIN_MENU = range(3)

# --- Helper Function for Markdown ---
def escape_markdown(text: str) -> str:
    """Escapes special characters for Telegram's MarkdownV2."""
    if not isinstance(text, str):
        text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# --- Google Drive API Logic ---
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DRIVE_SERVICE = None

def get_drive_service():
    """Initializes and returns the Google Drive API service."""
    global DRIVE_SERVICE
    if DRIVE_SERVICE:
        return DRIVE_SERVICE
    try:
        from google.oauth2 import service_account
        creds_json = json.loads(SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            creds_json, scopes=SCOPES)
        service = build("drive", "v3", credentials=creds)
        DRIVE_SERVICE = service
        logger.info("Google Drive service initialized successfully.")
        return service
    except Exception as e:
        logger.error(f"An error occurred initializing the Drive service: {e}")
        return None

# --- Google Drive Helper Functions ---
async def find_item_id_in_parent(name, parent_id, is_folder=True):
    """Finds a file or folder by name within a parent folder."""
    service = get_drive_service()
    if not service: return None
    mime_type_query = "mimeType = 'application/vnd.google-apps.folder'" if is_folder else "mimeType != 'application/vnd.google-apps.folder'"
    try:
        # Use case-insensitive search for folder names
        query = f"lower(name) = '{name.lower()}' and '{parent_id}' in parents and trashed = false and {mime_type_query}"
        response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = response.get('files', [])
        return files[0].get('id') if files else None
    except HttpError as error:
        logger.error(f"API Error finding '{name}': {error}")
        return None

async def list_folders_in_parent(parent_id):
    """Lists all folders within a parent folder."""
    service = get_drive_service()
    if not service: return []
    try:
        query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        response = service.files().list(q=query, spaces='drive', fields='files(name)').execute()
        return [item['name'] for item in response.get('files', [])]
    except HttpError as error:
        logger.error(f"API Error listing folders: {error}")
        return []

async def list_files_in_parent(parent_id):
    """Lists all files (not folders) within a parent folder, returning their name and ID."""
    service = get_drive_service()
    if not service: return []
    try:
        query = f"'{parent_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
        response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        return [{'name': item['name'], 'id': item['id']} for item in response.get('files', [])]
    except HttpError as error:
        logger.error(f"API Error listing files: {error}")
        return []

async def download_file_from_drive(file_id):
    """Downloads a file's content from Google Drive by its ID."""
    service = get_drive_service()
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        return fh
    except HttpError as error:
        logger.error(f"API Error downloading file: {error}")
        return None

async def resolve_path_to_id(path_parts):
    """Resolves a path like ['1st_Year', 'CSE'] to a Google Drive folder ID."""
    current_id = GOOGLE_DRIVE_ROOT_FOLDER_ID
    for part in path_parts:
        next_id = await find_item_id_in_parent(part, current_id, is_folder=True)
        if not next_id:
            logger.warning(f"Could not find folder part: '{part}' in path '{'/'.join(path_parts)}'")
            return None
        current_id = next_id
    return current_id

# --- Command Handlers ---
async def check_user_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if the user has completed the initial /start setup."""
    if 'year' not in context.user_data:
        await update.message.reply_text("Welcome\\! Please start by using the /start command to set your year and name\\.", parse_mode='MarkdownV2')
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to set up the user's year and name."""
    reply_keyboard = [["1st Year", "2nd Year"], ["3rd Year", "4th Year"]]
    await update.message.reply_text(
        "👋 Welcome\\! Let's get you set up\\.\n\n"
        "First, please select your academic year\\.",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode='MarkdownV2'
    )
    return SELECT_YEAR

async def select_year(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the year selection and asks for the user's name."""
    year_display = update.message.text
    year_folder_name = year_display.replace(" ", "_")
    context.user_data['year'] = year_folder_name
    context.user_data['year_display'] = year_display
    await update.message.reply_text(
        f"Great\\! You've selected *{escape_markdown(year_display)}*\\.\n\n"
        "Now, what's your name?",
        parse_mode='MarkdownV2',
        reply_markup=ReplyKeyboardRemove(),
    )
    return GET_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the name input and concludes the setup."""
    name = update.message.text
    context.user_data['name'] = name
    await update.message.reply_text(
        f"Hi {escape_markdown(name)}\\! You're all set up\\. You can now use the bot commands\\.\n\n"
        "Type /help to see what I can do\\.",
        parse_mode='MarkdownV2'
    )
    return ConversationHandler.END # End conversation after setup

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the help message with available commands."""
    if not await check_user_setup(update, context): return
    name = context.user_data.get('name', 'User')
    year_display = context.user_data.get('year_display', 'N/A')
    help_text = (
        f"👋 Hello {escape_markdown(name)}\\! Your current year is set to *{escape_markdown(year_display)}*\\.\n\n"
        "*Available Commands:*\n"
        "• `/branches` \\- Lists all branches for your year\\.\n"
        "• `/subjects <BRANCH>` \\- Lists subjects for a specific branch\\.\n"
        "• `/assignments <BRANCH> <SUBJECT>` \\- Shows all available assignment files\\.\n"
        "• `/notes <BRANCH> <SUBJECT>` \\- Shows all available note/unit files\\.\n"
        "• `/suggestion` \\- Send a suggestion or feedback\\.\n"
        "• `/start` \\- To reset your year and name\\.\n"
        "• `/cancel` \\- To end any active command\\."
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')

async def list_branches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists the available branches for the user's selected year."""
    if not await check_user_setup(update, context): return
    year = context.user_data['year']
    year_display = context.user_data['year_display']
    year_folder_id = await find_item_id_in_parent(year, GOOGLE_DRIVE_ROOT_FOLDER_ID)
    if not year_folder_id:
        await update.message.reply_text(f"🤷 No folder found for your year: `{escape_markdown(year_display)}`\\.", parse_mode='MarkdownV2')
        return
    branches = await list_folders_in_parent(year_folder_id)
    if not branches:
        await update.message.reply_text(f"🤷 No branches found for `{escape_markdown(year_display)}`\\.", parse_mode='MarkdownV2')
        return
    branch_list = "\n".join(f"• `{escape_markdown(item)}`" for item in sorted(branches))
    message = f"📚 *Available Branches for {escape_markdown(year_display)}:*\n\n{branch_list}"
    await update.message.reply_text(message, parse_mode='MarkdownV2')

async def list_subjects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists the subjects for a given branch."""
    if not await check_user_setup(update, context): return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/subjects <BRANCH>`")
        return
    year = context.user_data['year']
    year_display = context.user_data['year_display']
    branch = context.args[0].upper()
    branch_folder_id = await resolve_path_to_id([year, branch])
    if not branch_folder_id:
        await update.message.reply_text(f"❌ Branch folder for `{escape_markdown(branch)}` not found in `{escape_markdown(year_display)}`\\.", parse_mode='MarkdownV2')
        return
    subjects = await list_folders_in_parent(branch_folder_id)
    if not subjects:
        await update.message.reply_text(f"🤷 No subjects found for branch `{escape_markdown(branch)}`\\.", parse_mode='MarkdownV2')
        return
    subject_list = "\n".join(f"• `{escape_markdown(item)}`" for item in sorted(subjects))
    message = f"📖 *Subjects for {escape_markdown(year_display)}/{escape_markdown(branch)}:*\n\n{subject_list}"
    await update.message.reply_text(message, parse_mode='MarkdownV2')

async def list_items_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE, item_type: str):
    """Generic function to list files from 'assignments' or 'Notes' folders."""
    if not await check_user_setup(update, context): return
    if len(context.args) != 2:
        await update.message.reply_text(f"⚠️ Usage: `/{item_type.lower()} <BRANCH> <SUBJECT>`")
        return

    year = context.user_data['year']
    branch, subject = context.args[0].upper(), context.args[1].upper()

    await update.message.reply_text(f"🔎 Searching for {item_type} in `{escape_markdown(branch)}/{escape_markdown(subject)}`\\.\\.\\.", parse_mode='MarkdownV2')

    item_folder_id = await resolve_path_to_id([year, branch, subject, item_type])
    if not item_folder_id:
        await update.message.reply_text(f"❌ Could not find the `{item_type}` folder for `{escape_markdown(branch)}/{escape_markdown(subject)}`\\.", parse_mode='MarkdownV2')
        return

    files = await list_files_in_parent(item_folder_id)
    if not files:
        await update.message.reply_text(f"🤷 No {item_type} found for `{escape_markdown(branch)}/{escape_markdown(subject)}`\\.", parse_mode='MarkdownV2')
        return

    keyboard = []
    for file in sorted(files, key=lambda x: x['name']):
        button = InlineKeyboardButton(text=file['name'], callback_data=file['id'])
        keyboard.append([button])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"📄 *Available {item_type} for {escape_markdown(branch)}/{escape_markdown(subject)}:*\n\n"
        "Click on a file to download it\\.",
        reply_markup=reply_markup,
        parse_mode='MarkdownV2'
    )

async def list_assignments_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /assignments command."""
    await list_items_interactive(update, context, item_type="assignments")

async def list_notes_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /notes command."""
    await list_items_interactive(update, context, item_type="Notes")


async def file_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the button click to download and send a file."""
    query = update.callback_query
    await query.answer("✅ Request received!")

    file_id = query.data
    
    # Find the button that was clicked to get the filename
    file_name = "file"
    for row in query.message.reply_markup.inline_keyboard:
        for button in row:
            if button.callback_data == file_id:
                file_name = button.text
                break

    placeholder_message = await query.message.reply_text(f"⏳ Getting *{escape_markdown(file_name)}*\\, please wait\\.\\.\\.", parse_mode='MarkdownV2')

    file_content = await download_file_from_drive(file_id)
    if file_content:
        service = get_drive_service()
        file_metadata = service.files().get(fileId=file_id, fields='name').execute()
        actual_file_name = file_metadata.get('name', 'file')

        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=file_content,
            filename=actual_file_name
        )
        await placeholder_message.delete()
        await query.edit_message_text(text=f"✅ Download started for: *{escape_markdown(actual_file_name)}*", parse_mode='MarkdownV2')
    else:
        await placeholder_message.edit_text("⚠️ Error downloading the file from Google Drive\\.", parse_mode='MarkdownV2')

async def suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provides a link to a suggestion form."""
    await update.message.reply_text(
        "Got a suggestion or want to report an issue? Please fill out this form:\n\n"
        "https://forms.gle/FecbVJn69qDcsKcP8"
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current conversation."""
    await update.message.reply_text(
        "Operation cancelled\\.", reply_markup=ReplyKeyboardRemove(), parse_mode='MarkdownV2'
    )
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs errors and sends a user-friendly message."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(context.error, TimedOut):
        if update and hasattr(update, 'message'):
            await update.message.reply_text("We're experiencing a delay. Please try your request again in a moment.")
        return
    if isinstance(context.error, TelegramError):
        logger.warning(f"Telegram API Error: {context.error.message}")
        return

# --- Main Bot Execution (Webhook Version) ---

if not get_drive_service():
    logger.critical("Could not initialize Google Drive service. Exiting.")
    exit()

application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        SELECT_YEAR: [MessageHandler(filters.Regex(r"^(1st|2nd|3rd|4th) Year$"), select_year)],
        GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_user=True,
    per_chat=True,
    # Allow other handlers to be used while the conversation is active in a different state
    allow_reentry=True
)

application.add_handler(conv_handler)
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("branches", list_branches))
application.add_handler(CommandHandler("subjects", list_subjects))
application.add_handler(CommandHandler("assignments", list_assignments_interactive))
application.add_handler(CommandHandler("notes", list_notes_interactive))
application.add_handler(CommandHandler("suggestion", suggestion))
application.add_handler(CallbackQueryHandler(file_button_callback))
application.add_error_handler(error_handler)

# --- Initialize Application for Webhook ---
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

loop.run_until_complete(application.initialize())

# --- Flask App for Webhook Endpoint ---
flask_app = Flask(__name__)
app = WsgiToAsgi(flask_app)

@flask_app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
async def webhook() -> str:
    """This endpoint listens for updates from Telegram."""
    try:
        update = Update.de_json(request.get_json(), application.bot)
        await application.process_update(update)
        return "OK"
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        return "Error", 500
