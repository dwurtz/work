"""Signal type for all collectors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Signal:
    """A single piece of context collected from the desktop environment."""

    source: str  # "imessage", "whatsapp", "chrome", "clipboard", "screenshot", "calendar", "active_app", "email", "drive", "tasks"
    sender: str  # person name, app name, or URL
    text: str  # content (max 500 chars)
    timestamp: datetime
    id_key: str  # dedup identifier
