"""
api/routes/misc.py
~~~~~~~~~~~~~~~~~~
Miscellaneous FastAPI routes:
  GET /payment-success  – browser redirect page after Razorpay checkout
  GET /keep-alive       – uptime-monitor ping endpoint
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger("unieval")
router = APIRouter()

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


@router.get("/payment-success", response_class=HTMLResponse)
async def payment_success(request: Request) -> HTMLResponse:
    logger.info("User redirected to success page. Params: %s", dict(request.query_params))
    return HTMLResponse(content=_SUCCESS_HTML)


@router.get("/keep-alive")
async def keep_alive() -> dict:
    return {"status": "I am awake!"}
