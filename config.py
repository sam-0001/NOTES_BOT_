# config.py

import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Essential Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_DRIVE_ROOT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID")
SERVICE_ACCOUNT_ENV = os.getenv("SERVICE_ACCOUNT_JSON")  # Can be a path OR raw JSON

# --- Bot Settings ---
# Path for the persistence file on Render's persistent disk
PERSISTENCE_FILEPATH = "/data/bot_user_data.json"

# --- Unique Greetings ---
GREETINGS = [
    "Hello", "Hi there", "Welcome back", "Hey", "Good to see you again",
    "Greetings", "Nice to see you"
]

# --- Telegram Bot Conversation States ---
ASK_YEAR, ASK_BRANCH, ASK_NAME = range(3)

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
# Silence the noisy httpx logger to avoid exposing the bot token in logs
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
