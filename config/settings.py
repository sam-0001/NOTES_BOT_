"""
config/settings.py
~~~~~~~~~~~~~~~~~~
Central place for all environment-variable configuration.
Import from here instead of calling os.getenv() scattered across the codebase.
"""

import logging
import os

from dotenv import load_dotenv
from telebot import apihelper

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN: str       = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int        = int(os.getenv("ADMIN_ID", "0"))
STORAGE_GROUP_ID: str = os.getenv("STORAGE_GROUP_ID", "")

# ── Razorpay ──────────────────────────────────────────────────────────────────
RAZORPAY_KEY_ID: str        = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET: str    = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

# ── Server ────────────────────────────────────────────────────────────────────
PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
PORT: int            = int(os.getenv("PORT", "8000"))

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URI: str = os.getenv("MONGO_URI", "")

# ── Telebot network timeouts ──────────────────────────────────────────────────
apihelper.CONNECT_TIMEOUT = 30
apihelper.READ_TIMEOUT    = 300

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("unieval")
logger.info("ADMIN_ID loaded as: %d", ADMIN_ID)
