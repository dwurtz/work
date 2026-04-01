"""Entry point for the work web dashboard."""

from __future__ import annotations

import uvicorn


def start(host: str = "127.0.0.1", port: int = 5050) -> None:
    """Start the FastAPI server."""
    uvicorn.run("work.web.app:app", host=host, port=port)
