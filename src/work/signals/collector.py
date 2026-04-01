"""SignalCollector -- orchestrates all signal sources with deduplication."""

from __future__ import annotations

import logging
from collections import deque
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

    def __init__(self, history_size: int = 100) -> None:
        self._seen_ids: set[str] = set()
        self._last_app: str = ""
        self._last_title: str = ""
        self._screenshot_counter: int = 0
        self._screenshot_every: int = 1  # screenshot every collection cycle (~2s)
        self.recent_history: deque[Signal] = deque(maxlen=history_size)

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

        # Chrome tabs — disabled due to AppleScript profile bug
        # (only sees one profile, reports wrong active tab)
        # Active tab is captured via active_app window title instead
        # try:
        #     raw.extend(collect_chrome_tabs())
        # except Exception:
        #     log.exception("Chrome collector error")

        # Clipboard
        try:
            clip = collect_clipboard()
            if clip:
                raw.append(clip)
        except Exception:
            log.exception("Clipboard collector error")

        # Active app / window — capture once, reuse for screenshot decision
        current_app = ""
        current_title = ""
        try:
            current_app, current_title = get_active_app()
            if current_app and current_app != "Unknown" and current_app not in IGNORED_APPS:
                text = f"Active app: {current_app}"
                if current_title:
                    text += f" -- {current_title}"
                raw.append(
                    Signal(
                        source="active_app",
                        sender="system",
                        text=text[:500],
                        timestamp=datetime.now(),
                        id_key=f"app-{current_app}-{current_title}",
                    )
                )
        except Exception:
            log.exception("Active app collector error")

        # Screenshot — on context change OR every ~10 seconds
        try:
            self._screenshot_counter += 1
            context_changed = self.should_screenshot(current_app, current_title)
            periodic = self._screenshot_counter >= self._screenshot_every

            if context_changed or periodic:
                self._screenshot_counter = 0
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
                self.recent_history.append(sig)

        return new_signals

    def get_unmatched_history_summary(self, matched_ids: set[str]) -> str:
        """Return a text summary of recent signals that were NOT matched to any goal."""
        unmatched = [s for s in self.recent_history if s.id_key not in matched_ids]
        if not unmatched:
            return ""
        lines = []
        for s in unmatched[-30:]:  # last 30 unmatched
            ts = s.timestamp.strftime("%H:%M")
            lines.append(f"[{ts}] [{s.source}] {s.sender}: {s.text[:100]}")
        return "\n".join(lines)

    def should_screenshot(self, app: str, title: str) -> bool:
        """Return True if app/title changed since last check."""
        if app in IGNORED_APPS:
            changed = False
        else:
            changed = app != self._last_app or title != self._last_title
        self._last_app = app
        self._last_title = title
        return changed
