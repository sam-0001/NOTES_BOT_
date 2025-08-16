import os
import requests
from dotenv import load_dotenv

# Load environment variables from .env file for local testing
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")

if not all([TELEGRAM_BOT_TOKEN, RENDER_EXTERNAL_HOSTNAME]):
    print("ERROR: Missing TELEGRAM_BOT_TOKEN or RENDER_EXTERNAL_HOSTNAME environment variables.")
else:
    # Construct the webhook URL
    webhook_url = f"https://{RENDER_EXTERNAL_HOSTNAME}/{TELEGRAM_BOT_TOKEN}"
    
    # URL to set the webhook
    set_webhook_api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook?url={webhook_url}"

    try:
        response = requests.get(set_webhook_api_url)
        response_json = response.json()
        
        if response_json.get("ok"):
            print(f"Webhook set successfully to: {webhook_url}")
            print(f"Response: {response_json.get('description')}")
        else:
            print(f"Error setting webhook: {response_json.get('description')}")

    except Exception as e:
        print(f"An error occurred: {e}")
