import requests
import os

# IMPORTANT: Set this as a temporary environment variable in Render
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo"

try:
    response = requests.get(url)
    data = response.json()
    if data.get("ok"):
        print("--- Webhook Info ---")
        print(f"URL: {data['result'].get('url')}")
        print(f"Pending Updates: {data['result'].get('pending_update_count')}")
        if data['result'].get('last_error_message'):
            print(f"Last Error: {data['result'].get('last_error_message')}")
    else:
        print(f"Error checking webhook: {data.get('description')}")
except Exception as e:
    print(f"An error occurred: {e}")
