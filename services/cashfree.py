"""
services/cashfree.py
~~~~~~~~~~~~~~~~~~~~
Pure-HTTP Cashfree Payment Gateway integration (PG v2023-08-01).
Responsibilities:
1. Create a payment link or hosted checkout session URL.
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


def _get_api_endpoint(resource: str = "links") -> str:
    """Return Cashfree endpoint based on environment and resource (links or orders)."""
    is_test = CASHFREE_ENV in ("SANDBOX", "TEST") or CASHFREE_APP_ID.startswith("TEST")
    base = "https://sandbox.cashfree.com/pg" if is_test else "https://api.cashfree.com/pg"
    return f"{base}/{resource}"


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


def _create_via_orders_api(
    chat_id: str,
    subject_id: str,
    subject_name: str,
    price_inr: int,
    section_idx: int | None = None,
    section_name: str | None = None,
) -> str:
    """
    Fallback when Cashfree's Payment Links API is not enabled on merchant account.
    Uses standard Cashfree Orders API (POST /pg/orders) and returns the hosted checkout URL.
    """
    description = f"Purchase: {subject_name}"
    order_tags: dict[str, str] = {
        "chat_id": str(chat_id),
        "subject_id": str(subject_id),
    }
    if section_idx is not None:
        description = f"Purchase: {subject_name} - {section_name or 'Section'}"
        order_tags["section_idx"] = str(section_idx)

    ts = int(time.time())
    safe_cid = str(chat_id).replace("-", "m")
    uid = uuid.uuid4().hex[:6]
    order_id = f"ord_{safe_cid[:15]}_{ts}_{uid}"[:45]

    phone = _get_customer_phone(chat_id)

    payload: dict = {
        "order_id": order_id,
        "order_amount": float(price_inr),
        "order_currency": "INR",
        "customer_details": {
            "customer_id": f"tg_{chat_id}"[:50],
            "customer_phone": phone,
        },
        "order_tags": order_tags,
        "order_note": description[:100],
    }

    if PUBLIC_BASE_URL:
        payload["order_meta"] = {
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

    endpoint = _get_api_endpoint("orders")
    logger.info("Creating Cashfree Order fallback for chat_id=%s, amount=₹%s", chat_id, price_inr)

    resp = requests.post(endpoint, json=payload, headers=headers, timeout=15)
    if not resp.ok:
        logger.error("Cashfree Orders API error (%d): %s", resp.status_code, resp.text)
        raise RuntimeError(f"Cashfree API error {resp.status_code}: {resp.text}")

    resp_data = resp.json()
    session_id = resp_data.get("payment_session_id")
    if not session_id:
        logger.error("Cashfree response missing payment_session_id: %s", resp_data)
        raise RuntimeError(f"Cashfree response missing payment_session_id: {resp_data}")

    base_url = PUBLIC_BASE_URL.rstrip("/") if PUBLIC_BASE_URL else ""
    return f"{base_url}/checkout?session_id={session_id}"


def create_payment_link(
    chat_id: str,
    subject_id: str,
    subject_name: str,
    price_inr: int,
    section_idx: int | None = None,
    section_name: str | None = None,
) -> str:
    """
    Create a Cashfree payment link and return the checkout URL.
    Attempts /pg/links first; if the feature is not enabled on the merchant account,
    automatically falls back to /pg/orders.
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

    endpoint = _get_api_endpoint("links")
    logger.info("Creating Cashfree payment link for chat_id=%s, amount=₹%s", chat_id, price_inr)

    resp = requests.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=15,
    )

    if not resp.ok:
        # If payment links API is disabled on this Cashfree merchant account, fallback to Orders API
        if "link_creation_api" in resp.text or "feature_not_enabled" in resp.text:
            logger.info("PaymentLink API not enabled on Cashfree account; using Orders API fallback.")
            return _create_via_orders_api(
                chat_id=chat_id,
                subject_id=subject_id,
                subject_name=subject_name,
                price_inr=price_inr,
                section_idx=section_idx,
                section_name=section_name,
            )

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
    if not signature:
        logger.warning("Webhook verification: signature is empty or missing.")
        return False

    candidate_secrets = [
        s for s in (CASHFREE_SECRET_KEY, CASHFREE_WEBHOOK_SECRET)
        if s and not s.startswith("your_")
    ]
    if not candidate_secrets:
        logger.error("No valid Cashfree secret key configured; cannot verify signature.")
        return False

    # Standard Cashfree signature verification: timestamp + raw_body
    payloads = []
    if timestamp:
        payloads.append(timestamp.encode("utf-8") + body)
    payloads.append(body)

    for secret in candidate_secrets:
        for p in payloads:
            hmac_digest = hmac.new(
                secret.encode("utf-8"),
                p,
                hashlib.sha256,
            ).digest()

            expected_b64 = base64.b64encode(hmac_digest).decode("utf-8")
            if hmac.compare_digest(expected_b64, signature):
                return True

            expected_hex = hmac.new(
                secret.encode("utf-8"),
                p,
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(expected_hex, signature):
                return True

    logger.warning("Webhook signature mismatch for received signature %r", signature)
    return False
