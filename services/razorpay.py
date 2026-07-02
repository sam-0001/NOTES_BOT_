"""
services/razorpay.py
~~~~~~~~~~~~~~~~~~~~
Pure-HTTP Razorpay integration.
Only responsibility: create a payment link and return its short URL.
"""

import hashlib
import hmac

import requests

from config import (
    PUBLIC_BASE_URL,
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET,
)

_PAYMENT_LINKS_URL = "https://api.razorpay.com/v1/payment_links"


def create_payment_link(
    chat_id: str,
    subject_id: str,
    subject_name: str,
    price_inr: int,
    section_idx: int | None = None,
    section_name: str | None = None,
) -> str:
    """
    Create a Razorpay payment link and return the short URL.

    Raises RuntimeError if the API call fails.
    """
    description = f"Purchase: {subject_name}"
    notes = {
        "chat_id":    str(chat_id),
        "subject_id": str(subject_id),
    }
    if section_idx is not None:
        description = f"Purchase: {subject_name} - {section_name or 'Section'}"
        notes["section_idx"] = str(section_idx)

    payload = {
        "amount":          price_inr * 100,   # paise
        "currency":        "INR",
        "description":     description,
        "notify":          {"sms": False, "email": False},
        "reminder_enable": False,
        "notes":           notes,
        "callback_url":    f"{PUBLIC_BASE_URL}/payment-success",
        "callback_method": "get",
    }
    resp = requests.post(
        _PAYMENT_LINKS_URL,
        json=payload,
        auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
        timeout=15,
    )
    if not resp.ok:
        raise RuntimeError(f"Razorpay API error {resp.status_code}: {resp.text}")

    return resp.json()["short_url"]


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Return True if the HMAC-SHA256 signature matches the webhook secret."""
    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
