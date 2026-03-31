"""SignalCollector -- orchestrates all signal sources with deduplication."""

from __future__ import annotations

import logging
from datetime import datetime

from work.config import IGNORED_APPS, SCREENSHOT_APPS
from work.signals.active_app import get_active_app
from work.signals.chrome import collect_chrome_tabs
from work.signals.clipboard import collect_clipboard
from work.signals.imessage import collect_imessages
from work.signals.screenshot import capture_screenshot_if_changed
from work.signals.types import Signal
from work.signals.whatsapp import collect_whatsapp

log = logging.getLogger(__name__)


class SignalCollector:
    """Collects signals from all sources, deduplicating across calls."""

    def __init__(self) -> None:
        self._seen_ids: set[str] = set()
        self._last_app: str = ""
        self._last_title: str = ""

    def collect_all(self) -> list[Signal]:
        """
        Run all collectors, deduplicate against previously seen ids,
        return only new signals.
        """
        raw: list[Signal] = []

        # Messages
        try:
            raw.extend(collect_imessages())
        except Exception:
            log.exception("iMessage collector error")

        try:
            raw.extend(collect_whatsapp())
        except Exception:
            log.exception("WhatsApp collector error")

        # Chrome tabs
        try:
            raw.extend(collect_chrome_tabs())
        except Exception:
            log.exception("Chrome collector error")

        # Clipboard
        try:
            clip = collect_clipboard()
            if clip:
                raw.append(clip)
        except Exception:
            log.exception("Clipboard collector error")

        # Active app / window
        try:
            app_name, win_title = get_active_app()
            if app_name and app_name != "Unknown" and app_name not in IGNORED_APPS:
                text = f"Active app: {app_name}"
                if win_title:
                    text += f" -- {win_title}"
                raw.append(
                    Signal(
                        source="active_app",
                        sender="system",
                        text=text[:500],
                        timestamp=datetime.now(),
                        id_key=f"app-{app_name}-{win_title}",
                    )
                )
        except Exception:
            log.exception("Active app collector error")

        # Screenshot (only if context changed)
        try:
            app_name, win_title = get_active_app()
            if self.should_screenshot(app_name, win_title):
                screen = capture_screenshot_if_changed()
                if screen:
                    raw.append(screen)
        except Exception:
            log.exception("Screenshot collector error")

        # Deduplicate
        new_signals: list[Signal] = []
        for sig in raw:
            if sig.id_key not in self._seen_ids:
                self._seen_ids.add(sig.id_key)
                new_signals.append(sig)

        return new_signals

    def should_screenshot(self, app: str, title: str) -> bool:
        """Return True if app/title changed since last check and app is screenshottable."""
        if app in IGNORED_APPS:
            return False
        if app not in SCREENSHOT_APPS:
            return False
        changed = app != self._last_app or title != self._last_title
        self._last_app = app
        self._last_title = title
        return changed
