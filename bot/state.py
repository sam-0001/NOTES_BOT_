"""
bot/state.py
~~~~~~~~~~~~
Simple in-memory state machine for the admin conversation flow.

State is keyed by `chat_id` (int) and stored in module-level dicts so
all handler modules share the same state without passing objects around.
"""

from __future__ import annotations

_admin_state:   dict[int, str]  = {}
_admin_context: dict[int, dict] = {}

# chat_id -> referral code seen in /start payload, held until registration
# completes (registration happens a message or two after /start).
_pending_referral: dict[int, str] = {}

# chat_id -> list of message_ids sent by the bot that are "transient"
# (menus / status lines) and should be swept away once a flow finishes,
# so the chat only keeps the final result.
_transient_msgs: dict[int, list[int]] = {}


def set_state(chat_id: int, state: str, **ctx) -> None:
    """Set the current state and optional context payload for an admin chat."""
    _admin_state[chat_id]   = state
    _admin_context[chat_id] = ctx


def clear_state(chat_id: int) -> None:
    """Clear state and context (call when a flow completes or is cancelled)."""
    _admin_state.pop(chat_id, None)
    _admin_context.pop(chat_id, None)


def get_state(chat_id: int) -> str | None:
    return _admin_state.get(chat_id)


def get_context(chat_id: int) -> dict:
    return _admin_context.get(chat_id, {})


# ---------------------------------------------------------------------------
# Pending referral (bridges /start payload -> registration)
# ---------------------------------------------------------------------------

def set_pending_referral(chat_id: int, ref_code: str) -> None:
    _pending_referral[chat_id] = ref_code


def pop_pending_referral(chat_id: int) -> str | None:
    return _pending_referral.pop(chat_id, None)


# ---------------------------------------------------------------------------
# Transient message tracking (chat-declutter)
# ---------------------------------------------------------------------------

def track_transient(chat_id: int, message_id: int) -> None:
    _transient_msgs.setdefault(chat_id, []).append(message_id)


def pop_transient_ids(chat_id: int) -> list[int]:
    return _transient_msgs.pop(chat_id, [])
