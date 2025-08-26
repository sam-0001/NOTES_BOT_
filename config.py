# config.py

import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Essential Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_DRIVE_ROOT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID")
SHARED_DRIVE_ID = os.getenv("SHARED_DRIVE_ID")
SERVICE_ACCOUNT_ENV = os.getenv("SERVICE_ACCOUNT_JSON")
OWNER_IDS = [int(id) for id in os.getenv("OWNER_IDS", "").split(',') if id]
FEEDBACK_GROUP_ID = int(os.getenv("FEEDBACK_GROUP_ID", 0))


# --- Bot Settings ---
PERSISTENCE_FILEPATH = "/data/db.json"

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
# Silence noisy httpx logger
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- TEMPORARILY ENABLE DEBUG LOGS FOR GOOGLE ---
# This will show detailed API request/response info.
# Remember to change this back to logging.WARNING after debugging.
logging.getLogger("googleapiclient.discovery").setLevel(logging.DEBUG)
logging.getLogger("google.auth.transport.requests").setLevel(logging.DEBUG)
# --- END OF DEBUG SECTION ---

logger = logging.getLogger(__name__)
