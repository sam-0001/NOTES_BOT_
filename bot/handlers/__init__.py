"""
bot/handlers/__init__.py
~~~~~~~~~~~~~~~~~~~~~~~~
Importing this package registers all handlers on the bot instance.
Call `import bot.handlers` (or `from bot import handlers`) once at startup.
"""

from . import commands   # noqa: F401
from . import messages   # noqa: F401
from . import callbacks  # noqa: F401
