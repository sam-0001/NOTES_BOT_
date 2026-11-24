"""
services/razorpay.py
~~~~~~~~~~~~~~~~~~~~
Backward compatibility wrapper for existing code.
Delegates to Cashfree payment service.
"""

from services.cashfree import create_payment_link, verify_webhook_signature  # noqa: F401
