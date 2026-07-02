"""
db/queries.py
~~~~~~~~~~~~~
All database query helpers.

Each async `_async_*` function is the true implementation; the matching
sync wrapper (no prefix) calls `run_async()` so that synchronous bot
handlers can use them without worrying about the event loop.
"""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from config import logger
from db import client
from db.client import run_async

# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------

async def async_fetch_all_subjects() -> list[dict]:
    cursor = client.subjects_col.find({}).sort("_id", 1)
    return await cursor.to_list(length=None)


async def async_fetch_subject(subject_id: str) -> dict | None:
    try:
        oid = ObjectId(subject_id.strip())
    except (InvalidId, Exception) as exc:
        logger.error("Invalid subject_id: %r — %s", subject_id, exc)
        return None
    result = await client.subjects_col.find_one({"_id": oid})
    if result is None:
        logger.error("No subject found in DB for _id=%s", subject_id)
    return result


def fetch_all_subjects() -> list[dict]:
    return run_async(async_fetch_all_subjects())


def fetch_subject(subject_id: str) -> dict | None:
    return run_async(async_fetch_subject(subject_id))

# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

async def async_fetch_buyers(subject_id: str, section_idx: int | None = None) -> list[dict]:
    query: dict = {"subject_id": subject_id}
    if section_idx is not None:
        query["$or"] = [
            {"section_idx": section_idx},
            {"section_idx": {"$exists": False}},
            {"section_idx": None},
        ]
    cursor = client.orders_col.find(query)
    return await cursor.to_list(length=None)


async def async_fetch_user_orders(chat_id: str) -> list[dict]:
    cursor = client.orders_col.find({"chat_id": str(chat_id)})
    return await cursor.to_list(length=None)


async def async_record_order(chat_id: str, subject_id: str, section_idx: int | None = None) -> None:
    now = datetime.now(timezone.utc)
    query = {"chat_id": chat_id, "subject_id": subject_id}
    if section_idx is not None:
        query["section_idx"] = section_idx
    else:
        query["$or"] = [{"section_idx": {"$exists": False}}, {"section_idx": None}]

    order_doc = {
        "chat_id":       chat_id,
        "subject_id":    subject_id,
        "purchase_date": now,
    }
    if section_idx is not None:
        order_doc["section_idx"] = section_idx

    await client.orders_col.update_one(
        query,
        {"$setOnInsert": order_doc},
        upsert=True,
    )


async def async_grant_access(target_chat_id: str, subject_id: str, section_idx: int | None = None) -> None:
    now = datetime.now(timezone.utc)
    query = {"chat_id": str(target_chat_id), "subject_id": subject_id}
    if section_idx is not None:
        query["section_idx"] = section_idx
    else:
        query["$or"] = [{"section_idx": {"$exists": False}}, {"section_idx": None}]

    order_doc = {
        "chat_id":       str(target_chat_id),
        "subject_id":    subject_id,
        "purchase_date": now,
    }
    if section_idx is not None:
        order_doc["section_idx"] = section_idx

    await client.orders_col.update_one(
        query,
        {"$setOnInsert": order_doc},
        upsert=True,
    )


def fetch_buyers(subject_id: str, section_idx: int | None = None) -> list[dict]:
    return run_async(async_fetch_buyers(subject_id, section_idx))


def fetch_user_orders(chat_id: str) -> list[dict]:
    return run_async(async_fetch_user_orders(chat_id))

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

async def async_fetch_user_by_chat(chat_id: str) -> dict | None:
    return await client.users_col.find_one({"chat_id": chat_id})


async def async_fetch_user_by_mobile(mobile: str) -> dict | None:
    return await client.users_col.find_one({"mobile": mobile})


async def async_upsert_user(chat_id: str, mobile: str) -> bool:
    """Register or update a user. Returns True if this was a brand-new user."""
    existing = await client.users_col.find_one({"chat_id": chat_id})
    await client.users_col.update_one(
        {"chat_id": chat_id},
        {
            "$set": {"mobile": mobile, "registered_at": datetime.now(timezone.utc)},
            "$setOnInsert": {"referral_count": 0, "reward_claims": 0},
        },
        upsert=True,
    )
    return existing is None


def fetch_user_by_chat(chat_id: str) -> dict | None:
    return run_async(async_fetch_user_by_chat(chat_id))


def fetch_user_by_mobile(mobile: str) -> dict | None:
    return run_async(async_fetch_user_by_mobile(mobile))

# ---------------------------------------------------------------------------
# Subjects – mutations
# ---------------------------------------------------------------------------

async def async_insert_subject(name: str, price: int) -> None:
    await client.subjects_col.insert_one({"name": name, "price": price, "sections": []})


async def async_update_subject_name(subject_id: str, new_name: str) -> None:
    await client.subjects_col.update_one(
        {"_id": ObjectId(subject_id)},
        {"$set": {"name": new_name}},
    )


async def async_update_subject_price(subject_id: str, new_price: int) -> None:
    await client.subjects_col.update_one(
        {"_id": ObjectId(subject_id)},
        {"$set": {"price": new_price}},
    )


async def async_delete_subject(subject_id: str) -> None:
    await client.subjects_col.delete_one({"_id": ObjectId(subject_id)})


async def async_push_section(subject_id: str, section_name: str) -> None:
    await client.subjects_col.update_one(
        {"_id": ObjectId(subject_id)},
        {"$push": {"sections": {"name": section_name, "file_ids": [], "is_free": False, "price": 0}}},
    )


async def async_save_sections(subject_id: str, sections: list[dict]) -> None:
    """Overwrite the entire sections array (used for deletion)."""
    await client.subjects_col.update_one(
        {"_id": ObjectId(subject_id)},
        {"$set": {"sections": sections}},
    )


async def async_push_file_to_section(subject_id: str, section_idx: int, file_message_id: str) -> None:
    field = f"sections.{section_idx}.file_ids"
    await client.subjects_col.update_one(
        {"_id": ObjectId(subject_id)},
        {"$push": {field: file_message_id}},
    )


async def async_push_text_to_section(subject_id: str, section_idx: int, text: str) -> None:
    field = f"sections.{section_idx}.text_notes"
    await client.subjects_col.update_one(
        {"_id": ObjectId(subject_id)},
        {"$push": {field: text}},
    )


# ---------------------------------------------------------------------------
# Settings (single document: promo footer, referral threshold)
# ---------------------------------------------------------------------------

_SETTINGS_ID = "global"
_DEFAULT_SETTINGS = {"_id": _SETTINGS_ID, "promo_message": "", "referral_threshold": 5}


async def async_get_settings() -> dict:
    doc = await client.settings_col.find_one({"_id": _SETTINGS_ID})
    if not doc:
        doc = dict(_DEFAULT_SETTINGS)
        await client.settings_col.update_one(
            {"_id": _SETTINGS_ID}, {"$setOnInsert": doc}, upsert=True
        )
    doc.setdefault("promo_message", "")
    doc.setdefault("referral_threshold", 5)
    return doc


async def async_set_promo_message(text: str) -> None:
    await client.settings_col.update_one(
        {"_id": _SETTINGS_ID}, {"$set": {"promo_message": text}}, upsert=True
    )


async def async_set_referral_threshold(n: int) -> None:
    await client.settings_col.update_one(
        {"_id": _SETTINGS_ID}, {"$set": {"referral_threshold": n}}, upsert=True
    )


def get_settings() -> dict:
    return run_async(async_get_settings())


def set_promo_message(text: str) -> None:
    run_async(async_set_promo_message(text))


def set_referral_threshold(n: int) -> None:
    run_async(async_set_referral_threshold(n))


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------

async def async_record_referral(referrer_chat_id: str, referred_chat_id: str) -> bool:
    """
    Credit `referrer_chat_id` with one referral for `referred_chat_id`.
    Returns True if newly credited, False if this referred user was already
    counted before (prevents double-counting on re-registration) or if the
    referrer is trying to refer themselves.
    """
    if referrer_chat_id == referred_chat_id:
        return False
    try:
        await client.referrals_col.insert_one({
            "referrer_chat_id": referrer_chat_id,
            "referred_chat_id": referred_chat_id,
            "created_at": datetime.now(timezone.utc),
        })
    except Exception:
        # Unique index on referred_chat_id already has an entry.
        return False
    await client.users_col.update_one(
        {"chat_id": referrer_chat_id},
        {"$inc": {"referral_count": 1}},
        upsert=True,
    )
    return True


async def async_fetch_referral_count(chat_id: str) -> int:
    user = await client.users_col.find_one({"chat_id": chat_id})
    return int((user or {}).get("referral_count", 0) or 0)


async def async_fetch_reward_claims(chat_id: str) -> int:
    user = await client.users_col.find_one({"chat_id": chat_id})
    return int((user or {}).get("reward_claims", 0) or 0)


async def async_increment_reward_claims(chat_id: str) -> None:
    await client.users_col.update_one(
        {"chat_id": chat_id},
        {"$inc": {"reward_claims": 1}},
        upsert=True,
    )


def record_referral(referrer_chat_id: str, referred_chat_id: str) -> bool:
    return run_async(async_record_referral(referrer_chat_id, referred_chat_id))


def fetch_referral_count(chat_id: str) -> int:
    return run_async(async_fetch_referral_count(chat_id))


def fetch_reward_claims(chat_id: str) -> int:
    return run_async(async_fetch_reward_claims(chat_id))


def increment_reward_claims(chat_id: str) -> None:
    run_async(async_increment_reward_claims(chat_id))


async def async_fetch_all_user_chat_ids() -> list[str]:
    cursor = client.users_col.find({}, {"chat_id": 1})
    docs = await cursor.to_list(length=None)
    return [d["chat_id"] for d in docs if d.get("chat_id")]


def fetch_all_user_chat_ids() -> list[str]:
    return run_async(async_fetch_all_user_chat_ids())
