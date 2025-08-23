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

# ADD THIS LINE to load the owner IDs
OWNER_IDS = [int(id) for id in os.getenv("OWNER_IDS", "").split(',') if id]


# --- Bot Settings ---
# Path for the persistence file on Render's persistent disk
PERSISTENCE_FILEPATH = "/data/db.json" # Using db.json for TinyDB

# --- Unique Greetings ---
GREETINGS = [
    "Hello", "Hi there", "Welcome back", "Hey", "Good to see you again",
    "Greetings", "Nice to see you"
]

# --- Telegram Bot Conversation States ---
ASK_YEAR, ASK_BRANCH, ASK_NAME = range(3)

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s -
- %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
# Silence noisy library loggers to prevent log spam and token exposure
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("googleapiclient.discovery").setLevel(logging.WARNING)
logging.getLogger("google.auth.transport.requests").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
