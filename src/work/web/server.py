"""Entry point for the work web dashboard."""

from __future__ import annotations

import asyncio
import threading

import uvicorn

from work.config import WORK_HOME
from work.context import ScopeManager
from work.llm import GeminiClient
from work.monitor.loop import MonitorLoop
from work.signals import SignalCollector
from work.web.app import app

_monitor: MonitorLoop | None = None


def _start_monitor_background():
    """Start the monitor loop in a background thread with its own event loop."""
    global _monitor
    scope_manager = ScopeManager(WORK_HOME)
    gemini = GeminiClient()
    collector = SignalCollector()
    _monitor = MonitorLoop(scope_manager, gemini, collector)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_monitor.run(interactive=False))


def start(host: str = "127.0.0.1", port: int = 5050) -> None:
    """Start the FastAPI server with monitor running in background."""
    # Start monitor in background thread
    t = threading.Thread(target=_start_monitor_background, daemon=True)
    t.start()
    # Start web server
    uvicorn.run(app, host=host, port=port)
