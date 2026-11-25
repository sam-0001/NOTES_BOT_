"""
api/routes/misc.py
~~~~~~~~~~~~~~~~~~
Miscellaneous FastAPI routes:
  GET /checkout         – Cashfree hosted JS checkout redirect page
  GET /payment-success  – browser redirect page after Cashfree checkout
  GET /keep-alive       – uptime-monitor ping endpoint
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from config import CASHFREE_APP_ID, CASHFREE_ENV

logger = logging.getLogger("unieval")
router = APIRouter()

_CHECKOUT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Redirecting to Payment – UNIEVAL</title>
    <script src="https://sdk.cashfree.com/js/v3/cashfree.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            background: #f4f4f9;
            padding: 20px;
        }
        .card {
            background: #fff;
            border-radius: 16px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08);
            max-width: 400px;
            width: 100%;
            padding: 40px 24px;
            text-align: center;
        }
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #2563eb;
            border-radius: 50%;
            width: 48px;
            height: 48px;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        h2 { font-size: 20px; color: #1e293b; margin-bottom: 8px; }
        p { font-size: 14px; color: #64748b; margin-bottom: 24px; }
        .btn {
            display: none;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 12px 24px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="spinner"></div>
        <h2>Opening Payment Gateway...</h2>
        <p>Please wait, redirecting securely to Cashfree.</p>
        <button id="payBtn" class="btn">Click here if not redirected</button>
    </div>
    <script>
        const mode = "{{ mode }}";
        const cashfree = Cashfree({ mode: mode });
        const paymentSessionId = "{{ session_id }}";

        function launchCheckout() {
            cashfree.checkout({
                paymentSessionId: paymentSessionId,
                redirectTarget: "_self"
            }).then(function(result) {
                if (result && result.error) {
                    console.error("Payment error:", result.error);
                    document.getElementById("payBtn").style.display = "inline-block";
                }
            });
        }

        window.addEventListener("load", launchCheckout);
        document.getElementById("payBtn").addEventListener("click", launchCheckout);
    </script>
</body>
</html>
"""

_SUCCESS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Payment Successful – UNIEVAL</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f4f4f9;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }
        .card {
            background: #fff;
            border-radius: 16px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            max-width: 420px;
            width: 100%;
            padding: 48px 32px;
            text-align: center;
        }
        .icon  { font-size: 64px; margin-bottom: 16px; }
        h1     { color: #28a745; font-size: 24px; margin-bottom: 12px; }
        p      { color: #555; font-size: 15px; line-height: 1.6; margin-top: 8px; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">✅</div>
        <h1>Payment Successful!</h1>
        <p>Thank you for your purchase.</p>
        <p>You can safely close this window and go back to Telegram to pick your section and download your notes!</p>
    </div>
</body>
</html>
"""


@router.get("/checkout", response_class=HTMLResponse)
async def checkout(request: Request, session_id: str = "") -> HTMLResponse:
    if not session_id:
        return HTMLResponse(content="<h3>Error: Missing payment session ID.</h3>", status_code=400)

    is_test = CASHFREE_ENV in ("SANDBOX", "TEST") or CASHFREE_APP_ID.startswith("TEST")
    mode = "sandbox" if is_test else "production"

    html = (
        _CHECKOUT_HTML
        .replace("{{ mode }}", mode)
        .replace("{{ session_id }}", session_id)
    )
    return HTMLResponse(content=html)


@router.get("/payment-success", response_class=HTMLResponse)
async def payment_success(request: Request) -> HTMLResponse:
    logger.info("User redirected to success page. Params: %s", dict(request.query_params))
    return HTMLResponse(content=_SUCCESS_HTML)


@router.get("/keep-alive")
async def keep_alive() -> dict:
    return {"status": "I am awake!"}
