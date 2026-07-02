"""
main.py
~~~~~~~
Entry point for the UNIEVAL backend.

Run with:
    python main.py
or:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import uvicorn

from api.app import create_app
from config import PORT

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
    )
