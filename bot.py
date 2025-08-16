import os
import logging
import sqlite3
import re
import io
import json
from pathlib import Path
import asyncio

# Third-party libraries
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.error import TimedOut, TelegramError

# Google Drive Imports
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

# NEW: Webhook-related imports
from flask import Flask, request

# --- Configuration and Setup ---
# Use a data directory that works with Render's persistent disk
DATA_DIR = Path(os.getenv("RENDER_DISK_PATH", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True) # Ensure the directory exists

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_DRIVE_ROOT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID")
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
# NEW: Get hostname for webhook URL from Render's environment variables
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")

# Check for essential environment variables
if not all([TELEGRAM_BOT_TOKEN, GOOGLE_DRIVE_ROOT_FOLDER_ID, SERVICE_ACCOUNT_JSON]):
    raise ValueError("One or more required environment variables are missing (TELEGRAM_BOT_TOKEN, GOOGLE_DRIVE_ROOT_FOLDER_ID, SERVICE_ACCOUNT_JSON).")

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

# --- Database Management (Caching with Year) ---
DB_FILE = DATA_DIR / "file_cache.db"

def setup_database():
    """Initializes the SQLite database for caching."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assignment_cache (
            id INTEGER PRIMARY KEY, year TEXT, branch TEXT, subject TEXT, assignment_number INTEGER,
            telegram_file_id TEXT, UNIQUE(year, branch, subject, assignment_number)
        )""")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS note_cache (
            id INTEGER PRIMARY KEY, year TEXT, branch TEXT, subject TEXT, note_number INTEGER,
            telegram_file_id TEXT, UNIQUE(year, branch, subject, note_number)
        )""")
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at: {DB_FILE}")

def get_cached_assignment_id(year, branch, subject, assignment_number):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT telegram_file_id FROM assignment_cache WHERE year = ? AND branch = ? AND subject = ? AND assignment_number = ?",
        (year, branch.upper(), subject.upper(), assignment_number)
    )
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def cache_assignment_id(year, branch, subject, assignment_number, file_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO assignment_cache (year, branch, subject, assignment_number, telegram_file_id) VALUES (?, ?, ?, ?, ?)",
        (year, branch.upper(), subject.upper(), assignment_number, file_id)
    )
    conn.commit()
    conn.close()

def get_cached_note_id(year, branch, subject, note_number):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT telegram_file_id FROM note_cache WHERE year = ? AND branch = ? AND subject = ? AND note_number = ?",
        (year, branch.upper(), subject.upper(), note_number)
    )
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def cache_note_id(year, branch, subject, note_number, file_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO note_cache (year, branch, subject, note_number, telegram_file_id) VALUES (?, ?, ?, ?, ?)",
        (year, branch.upper(), subject.upper(), note_number, file_id)
    )
    conn.commit()
    conn.close()

# --- Google Drive API Logic ---
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DRIVE_SERVICE = None

def get_drive_service():
    """Initializes and returns the Google Drive API service from an environment variable."""
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
    # (This function is unchanged)
    service = get_drive_service()
    if not service: return None
    mime_type_query = "mimeType = 'application/vnd.google-apps.folder'" if is_folder else "mimeType != 'application/vnd.google-apps.folder'"
    try:
        query = f"name = '{name}' and '{parent_id}' in parents and trashed = false and {mime_type_query}"
        response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = response.get('files', [])
        return files[0].get('id') if files else None
    except HttpError as error:
        logger.error(f"API Error finding '{name}': {error}")
        return None

async def list_folders_in_parent(parent_id):
    # (This function is unchanged)
    service = get_drive_service()
    if not service: return []
    try:
        query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        response = service.files().list(q=query, spaces='drive', fields='files(name)').execute()
        return [item['name'] for item in response.get('files', [])]
    except HttpError as error:
        logger.error(f"API Error listing folders: {error}")
        return []

async def download_file_from_drive(file_id):
    # (This function is unchanged)
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
    # (This function is unchanged)
    current_id = GOOGLE_DRIVE_ROOT_FOLDER_ID
    for part in path_parts:
        next_id = await find_item_id_in_parent(part, current_id, is_folder=True)
        if not next_id:
            logger.warning(f"Could not find folder part: '{part}' in path '{'/'.join(path_parts)}'")
            return None
        current_id = next_id
    return current_id

# --- Command Handlers ---
# ALL of your command handlers (start, select_year, get_name, help_command,
# list_branches, list_subjects, list_assignments, get_assignment, etc.)
# remain EXACTLY THE SAME. No changes are needed in them.
# I'm omitting them here for brevity, but you should copy them all into this script.

async def check_user_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if 'year' not in context.user_data:
        await update.message.reply_text("Welcome\\! Please start by using the /start command to set your year and name\\.")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # (This function is unchanged)
    # ...

async def select_year(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # (This function is unchanged)
    # ...

# ... and so on for all your other command handler functions ...


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (This function is unchanged)
    logger.error("Exception while handling an update:", exc_info=context.error)
    # ...

# --- NEW: Main Bot Execution (Webhook Version) ---

# Initialize the bot application
if not get_drive_service():
    logger.critical("Could not initialize Google Drive service. Exiting.")
    exit()
setup_database()

application = (
    Application.builder()
    .token(TELEGRAM_BOT_TOKEN)
    .connect_timeout(30)
    .read_timeout(30)
    .build()
)

# Add all your command and conversation handlers
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        SELECT_YEAR: [MessageHandler(filters.Regex(r"^(1st|2nd|3rd|4th) Year$"), select_year)],
        GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        MAIN_MENU: [
            CommandHandler("help", help_command),
            CommandHandler("branches", list_branches),
            CommandHandler("subjects", list_subjects),
            CommandHandler("assignments", list_assignments),
            CommandHandler("get", get_assignment),
            CommandHandler("notes", list_notes),
            CommandHandler("getnote", get_note),
            CommandHandler("suggestion", suggestion),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    per_user=True,
    per_chat=True
)

application.add_handler(conv_handler)
application.add_error_handler(error_handler)

# This is the main Flask app object that Gunicorn will run
app = Flask(__name__)

@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
async def webhook() -> str:
    """This endpoint listens for updates from Telegram."""
    try:
        update = Update.de_json(await request.get_json(), application.bot)
        await application.process_update(update)
        return "OK"
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        return "Error", 500

async def setup_bot():
    """Sets the webhook and starts the application."""
    if not RENDER_EXTERNAL_HOSTNAME:
        logger.warning("RENDER_EXTERNAL_HOSTNAME is not set. Cannot set webhook.")
        return

    # The webhook URL is your Render service URL + your bot token
    webhook_url = f"https://{RENDER_EXTERNAL_HOSTNAME}/{TELEGRAM_BOT_TOKEN}"
    
    # This asynchronous block runs the setup
    async with application:
        await application.bot.set_webhook(url=webhook_url)
        # The application's update processing will be handled by the webhook endpoint
        logger.info(f"Webhook has been set to {webhook_url}")

if __name__ == "__main__":
    # This block is mainly for local testing and to ensure the setup runs on startup
    # On Render, Gunicorn will start the 'app' object, and the bot setup will run once.
    loop = asyncio.get_event_loop()
    loop.run_until_complete(setup_bot())
    
    # For local testing, you can uncomment the following lines and run `python bot.py`
    # logger.info("Starting Flask app for local testing...")
    # app.run(port=8080, debug=True)
