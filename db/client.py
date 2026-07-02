"""
db/client.py
~~~~~~~~~~~~
Motor (async MongoDB) client lifecycle and collection references.
"""

from __future__ import annotations

import asyncio
import threading

import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from config import MONGO_URI, logger

# ---------------------------------------------------------------------------
# Module-level singletons (populated by init_db)
# ---------------------------------------------------------------------------

_motor_client: AsyncIOMotorClient | None = None

subjects_col:   AsyncIOMotorCollection | None = None
orders_col:     AsyncIOMotorCollection | None = None
users_col:      AsyncIOMotorCollection | None = None
settings_col:   AsyncIOMotorCollection | None = None
referrals_col:  AsyncIOMotorCollection | None = None

# We use a dedicated, thread-safe reference to the main event loop
_MAIN_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_LOCK = threading.Lock()


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Explicitly register the main running loop."""
    global _MAIN_LOOP
    with _LOOP_LOCK:
        _MAIN_LOOP = loop
        logger.info("Database bridge event loop registered successfully.")


def run_async(coro) -> object:
    """
    Run an async coroutine from a synchronous thread context.
    Falls back gracefully if the loop isn't explicitly registered yet.
    """
    global _MAIN_LOOP
    
    # 1. Try to use the explicitly registered lifespan loop
    loop = _MAIN_LOOP
    
    # 2. Fallback: Try to get the current running loop in this thread context
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    # 3. Last Resort: If no loop exists, create an isolated ephemeral loop
    if loop is None:
        try:
            return asyncio.run(coro)
        except RuntimeError:
            # If asyncio.run fails because a loop is present but unhandled
            loop = asyncio.get_event_loop()

    # Schedule and block until completion
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """Connect to MongoDB and create required indexes."""
    global _motor_client, subjects_col, orders_col, users_col, settings_col, referrals_col

    if not MONGO_URI:
        raise RuntimeError("MONGO_URI is not set in the environment.")

    logger.info("Initializing MongoDB connection...")
    _motor_client = AsyncIOMotorClient(
        MONGO_URI,
        serverSelectionTimeoutMS=8_000,
        tlsCAFile=certifi.where(),
    )
    
    # Ensure connection is verified before proceeding
    await _motor_client.admin.command("ping")

    db            = _motor_client["unieval"]
    subjects_col  = db["subjects"]
    orders_col    = db["orders"]
    users_col     = db["users"]
    settings_col  = db["settings"]
    referrals_col = db["referrals"]

    existing_indexes = await orders_col.index_information()
    if "chat_subject_unique" in existing_indexes:
        await orders_col.drop_index("chat_subject_unique")

    await orders_col.create_index(
        [("chat_id", 1), ("subject_id", 1), ("section_idx", 1)],
        name="chat_subject_section_unique",
        unique=True,
        background=True,
    )
    await users_col.create_index("mobile", unique=True, sparse=True)
    await users_col.create_index("chat_id", unique=True)
    await referrals_col.create_index("referred_chat_id", unique=True)
    await referrals_col.create_index("referrer_chat_id")

    logger.info("MongoDB connected and collection indexes verified.")


async def close_db() -> None:
    """Close the Motor client gracefully."""
    global _motor_client
    if _motor_client:
        _motor_client.close()
        _motor_client = None
        logger.info("MongoDB connection dropped.")
