"""
services/cashfree.py
~~~~~~~~~~~~~~~~~~~~
Pure-HTTP Cashfree Payment Gateway integration (PG v2023-08-01).
Responsibilities:
1. Create a payment link and return its hosted checkout URL.
2. Verify webhook signatures against the Cashfree secret key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid

import requests

from config import (
    CASHFREE_API_VERSION,
    CASHFREE_APP_ID,
    CASHFREE_ENV,
    CASHFREE_SECRET_KEY,
    CASHFREE_WEBHOOK_SECRET,
    PUBLIC_BASE_URL,
    logger,
)
from db.queries import fetch_user_by_chat


def _get_api_endpoint() -> str:
    """Return Cashfree payment links endpoint based on environment."""
    if CASHFREE_ENV in ("SANDBOX", "TEST") or CASHFREE_APP_ID.startswith("TEST"):
        return "https://sandbox.cashfree.com/pg/links"
    return "https://api.cashfree.com/pg/links"


def _get_customer_phone(chat_id: str) -> str:
    """Retrieve 10-digit customer phone number or fallback."""
    try:
        user = fetch_user_by_chat(str(chat_id))
        if user and user.get("mobile"):
            digits = "".join(filter(str.isdigit, str(user["mobile"])))
            if len(digits) >= 10:
                return digits[-10:]
    except Exception as exc:
        logger.warning("Could not fetch user phone for chat_id %s: %s", chat_id, exc)
    return "9999999999"


def create_payment_link(
    chat_id: str,
    subject_id: str,
    subject_name: str,
    price_inr: int,
    section_idx: int | None = None,
    section_name: str | None = None,
) -> str:
    """
    Create a Cashfree payment link and return the hosted checkout URL.

    Raises RuntimeError if the API call fails or keys are missing.
    """
    if not CASHFREE_APP_ID or not CASHFREE_SECRET_KEY:
        raise RuntimeError("Cashfree credentials (CASHFREE_APP_ID / CASHFREE_SECRET_KEY) are not set in .env")

    description = f"Purchase: {subject_name}"
    link_notes: dict[str, str] = {
        "chat_id": str(chat_id),
        "subject_id": str(subject_id),
    }
    if section_idx is not None:
        description = f"Purchase: {subject_name} - {section_name or 'Section'}"
        link_notes["section_idx"] = str(section_idx)

    # Cashfree link_id: alphanumeric, underscores, hyphens, max 50 chars
    uid = uuid.uuid4().hex[:6]
    ts = int(time.time())
    safe_cid = str(chat_id).replace("-", "m")
    link_id = f"link_{safe_cid[:15]}_{ts}_{uid}"[:50]

    phone = _get_customer_phone(chat_id)

    payload: dict = {
        "link_id": link_id,
        "link_amount": float(price_inr),
        "link_currency": "INR",
        "link_purpose": description[:100],
        "customer_details": {
            "customer_id": f"tg_{chat_id}"[:50],
            "customer_phone": phone,
        },
        "link_notes": link_notes,
    }

    if PUBLIC_BASE_URL:
        payload["link_meta"] = {
            "notify_url": f"{PUBLIC_BASE_URL}/cashfree-webhook",
            "return_url": f"{PUBLIC_BASE_URL}/payment-success?order_id={{order_id}}",
        }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-api-version": CASHFREE_API_VERSION,
        "x-client-id": CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET_KEY,
    }

    endpoint = _get_api_endpoint()
    logger.info("Creating Cashfree payment link for chat_id=%s, amount=₹%s", chat_id, price_inr)

    resp = requests.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=15,
    )

    if not resp.ok:
        logger.error("Cashfree API error (%d): %s", resp.status_code, resp.text)
        raise RuntimeError(f"Cashfree API error {resp.status_code}: {resp.text}")

    resp_data = resp.json()
    link_url = resp_data.get("link_url")
    if not link_url:
        logger.error("Cashfree response missing link_url: %s", resp_data)
        raise RuntimeError(f"Cashfree response missing link_url: {resp_data}")

    return link_url


def verify_webhook_signature(body: bytes, signature: str, timestamp: str = "") -> bool:
    """
    Verify the webhook signature against CASHFREE_SECRET_KEY / CASHFREE_WEBHOOK_SECRET.
    Cashfree computes HMAC-SHA256 of (timestamp + raw_body) and encodes it in base64 or hex.
    """
    secret = CASHFREE_WEBHOOK_SECRET or CASHFREE_SECRET_KEY
    if not secret:
        logger.error("Cashfree secret key not configured; cannot verify signature.")
        return False

    if not signature:
        return False

    # Standard Cashfree signature verification: timestamp + raw_body
    if timestamp:
        signed_payload = timestamp.encode("utf-8") + body
    else:
        signed_payload = body

    hmac_digest = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).digest()

    expected_b64 = base64.b64encode(hmac_digest).decode("utf-8")
    expected_hex = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_b64, signature) or hmac.compare_digest(expected_hex, signature)
