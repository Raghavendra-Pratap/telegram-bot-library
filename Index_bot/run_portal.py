#!/usr/bin/env python3
"""Run the watch portal web server."""
from __future__ import annotations

import uvicorn

from config import Config

if __name__ == "__main__":
    Config.validate()
    uvicorn.run(
        "portal.api:app",
        host=Config.PORTAL_HOST,
        port=Config.PORTAL_PORT,
        reload=False,
    )
