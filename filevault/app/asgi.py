"""Server entrypoint: `uvicorn app.asgi:app`.

Separate from app.main so that importing the application factory -- which the
tests do -- does not build an app, and so a missing vault fails when the server
starts rather than when anything merely imports the module.
"""

from __future__ import annotations

import logging

from .main import create_app

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = create_app()
