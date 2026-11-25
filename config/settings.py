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
_raw_storage = os.getenv("STORAGE_GROUP_ID", "").strip().strip('"').strip("'")
STORAGE_GROUP_ID: int | str = int(_raw_storage) if _raw_storage.lstrip("-").isdigit() else _raw_storage

# ── Cashfree ──────────────────────────────────────────────────────────────────
CASHFREE_APP_ID: str         = (
    os.getenv("CASHFREE_APP_ID")
    or os.getenv("CASHFREE_CLIENT_ID")
    or ""
)
CASHFREE_SECRET_KEY: str     = (
    os.getenv("CASHFREE_SECRET_KEY")
    or os.getenv("CASHFREE_CLIENT_SECRET")
    or ""
)
CASHFREE_WEBHOOK_SECRET: str = (
    os.getenv("CASHFREE_WEBHOOK_SECRET")
    or CASHFREE_SECRET_KEY
)
CASHFREE_API_VERSION: str    = os.getenv("CASHFREE_API_VERSION", "2023-08-01")
CASHFREE_ENV: str            = os.getenv("CASHFREE_ENV", "PRODUCTION").upper()

# Backward compatibility aliases
RAZORPAY_KEY_ID: str        = os.getenv("RAZORPAY_KEY_ID", CASHFREE_APP_ID)
RAZORPAY_KEY_SECRET: str    = os.getenv("RAZORPAY_KEY_SECRET", CASHFREE_SECRET_KEY)
RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", CASHFREE_WEBHOOK_SECRET)

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
logger.info("STORAGE_GROUP_ID loaded as: %r (type: %s)", STORAGE_GROUP_ID, type(STORAGE_GROUP_ID).__name__)
