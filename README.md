# UNIEVAL – Telegram EdTech Bot

A Telegram bot backend for selling and delivering study materials, built with:

- **pyTelegramBotAPI** – Telegram bot framework
- **FastAPI** – async web server / webhook receiver
- **Motor** – async MongoDB driver
- **Razorpay** – payment links (pure HTTP)

---

## Project Structure

```
unieval/
├── main.py                     # Entry point – FastAPI app + lifespan
├── .env.example                # Environment variable template
├── requirements.txt
│
├── config/
│   └── settings.py             # All env-var config in one place
│
├── db/
│   ├── client.py               # Motor connection, init/close
│   └── queries.py              # All DB query helpers (sync + async)
│
├── services/
│   ├── razorpay.py             # Payment link creation
│   └── broadcast.py            # New-material broadcast logic
│
├── bot/
│   ├── instance.py             # TeleBot singleton
│   ├── keyboards.py            # All keyboard builder functions
│   ├── state.py                # Admin state machine helpers
│   └── handlers/
│       ├── __init__.py         # Registers all handlers on the bot
│       ├── commands.py         # /start /help /my_notes /admin etc.
│       ├── messages.py         # Text / document / photo handler
│       └── callbacks.py        # Inline button callback handler
│
├── api/
│   ├── app.py                  # FastAPI app factory + lifespan
│   └── routes/
│       ├── __init__.py
│       ├── webhook.py          # POST /razorpay-webhook
│       └── misc.py             # GET /payment-success, /keep-alive
│
└── utils/
    └── sections.py             # get_sections() helper
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Fill in all values in .env
```

### 3. Run
```bash
python main.py
# or
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `ADMIN_ID` | Your Telegram numeric user ID |
| `STORAGE_GROUP_ID` | Telegram group ID used as file storage |
| `RAZORPAY_KEY_ID` | Razorpay API key ID |
| `RAZORPAY_KEY_SECRET` | Razorpay API key secret |
| `RAZORPAY_WEBHOOK_SECRET` | Razorpay webhook signing secret |
| `PUBLIC_BASE_URL` | Your server's public URL (for payment callbacks) |
| `MONGO_URI` | MongoDB connection string |

---

## Data Model

### Subject
```json
{
  "_id": "ObjectId",
  "name": "Engineering Maths",
  "price": 299,
  "sections": [
    { "name": "Unit 1", "file_ids": ["111", "222"], "is_free": true, "price": 0 },
    { "name": "Short Notes", "file_ids": ["333"], "is_free": false, "price": 99 }
  ]
}
```

### Order
```json
{ "chat_id": "123456", "subject_id": "ObjectId", "section_idx": 1, "purchase_date": "ISODate" }
```

Older/full-subject orders may omit `section_idx`; those orders unlock every section in that subject.

## Section Free/Paid Control

From `/admin`:

1. Open **Manage Sections**.
2. Select a subject.
3. Tap the settings button for a section.
4. Choose **Make Free** or **Make Paid / Set Price**.

Users can open a subject and see each section as unlocked, free, or locked with its own price. Razorpay section payments unlock only that section. If a subject is free but one section is paid, the paid section still requires payment before notes are delivered.

### User
```json
{ "chat_id": "123456", "mobile": "+911234567890", "registered_at": "ISODate" }
```
