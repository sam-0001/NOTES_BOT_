"""
bot/instance.py
~~~~~~~~~~~~~~~
Creates the single TeleBot instance used across the entire application.
Import `bot` from here everywhere – never instantiate TeleBot elsewhere.
"""

import telebot

from config import BOT_TOKEN

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
