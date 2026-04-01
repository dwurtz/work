"""SignalCollector -- orchestrates all signal sources with deduplication."""

from __future__ import annotations

import logging
import json
from collections import deque
from datetime import datetime
from pathlib import Path

from work.config import IGNORED_APPS, SCREENSHOT_APPS, WORK_HOME
from work.signals.active_app import get_active_app
from work.signals.calendar import collect_upcoming_events
from work.signals.chrome import collect_chrome_tabs
from work.signals.clipboard import collect_clipboard
from work.signals.drive import collect_recent_drive_activity
from work.signals.email import collect_recent_emails
from work.signals.imessage import collect_imessages
from work.signals.screenshot import capture_screenshot_if_changed
from work.signals.tasks import collect_pending_tasks
from work.signals.types import Signal
from work.signals.whatsapp import collect_whatsapp

log = logging.getLogger(__name__)


class SignalCollector:
    """Collects signals from all sources, deduplicating across calls."""

    def __init__(self, history_size: int = 10000) -> None:
        self._seen_ids: set[str] = set()
        self._last_app: str = ""
        self._last_title: str = ""
        self._screenshot_counter: int = 0
        self._screenshot_every: int = 1  # screenshot every collection cycle (~2s)
        self._email_counter: int = 0
        self._calendar_counter: int = 0
        self._drive_counter: int = 0
        self._tasks_counter: int = 0
        self._gws_every: int = 5  # run email/calendar/drive/tasks every 5th cycle (~15s)
        self.recent_history: deque[Signal] = deque(maxlen=history_size)
        self._signal_log_path = WORK_HOME / "signal_log.jsonl"
        self._load_history()

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

        # Email — every 5th cycle
        self._email_counter += 1
        if self._email_counter >= self._gws_every:
            self._email_counter = 0
            try:
                raw.extend(collect_recent_emails())
            except Exception:
                log.exception("Email collector error")

        # Calendar — every 5th cycle
        self._calendar_counter += 1
        if self._calendar_counter >= self._gws_every:
            self._calendar_counter = 0
            try:
                raw.extend(collect_upcoming_events())
            except Exception:
                log.exception("Calendar collector error")

        # Drive — every 5th cycle
        self._drive_counter += 1
        if self._drive_counter >= self._gws_every:
            self._drive_counter = 0
            try:
                raw.extend(collect_recent_drive_activity())
            except Exception:
                log.exception("Drive collector error")

        # Tasks — every 5th cycle
        self._tasks_counter += 1
        if self._tasks_counter >= self._gws_every:
            self._tasks_counter = 0
            try:
                raw.extend(collect_pending_tasks())
            except Exception:
                log.exception("Tasks collector error")

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
                # Don't persist screenshot signals here — they contain raw file paths.
                # The monitor loop persists them after vision analysis.
                if sig.source != "screenshot":
                    self._persist_signal(sig)

        return new_signals

    def get_unmatched_history_summary(self, matched_ids: set[str], max_recent: int = 50, max_older: int = 30) -> str:
        """Return a summary of unmatched signals: recent ones in detail, older ones compressed by theme."""
        unmatched = [s for s in self.recent_history if s.id_key not in matched_ids]
        if not unmatched:
            return ""

        now = datetime.now()
        recent = []   # last hour
        older = []    # older than 1 hour

        for s in unmatched:
            age = (now - s.timestamp).total_seconds()
            if age < 3600:
                recent.append(s)
            else:
                older.append(s)

        lines = []

        # Recent: show detail
        if recent:
            lines.append("RECENT (last hour):")
            for s in recent[-max_recent:]:
                ts = s.timestamp.strftime("%H:%M")
                lines.append(f"  [{ts}] [{s.source}] {s.sender}: {s.text[:100]}")

        # Older: compress — just show source counts and sample texts
        if older:
            lines.append(f"\nOLDER ({len(older)} signals over past sessions):")
            # Group by date
            by_date: dict[str, list[Signal]] = {}
            for s in older[-500:]:  # last 500 older signals
                day = s.timestamp.strftime("%b %d")
                by_date.setdefault(day, []).append(s)
            for day, sigs in sorted(by_date.items()):
                samples = [s.text[:60] for s in sigs[-max_older:]]
                lines.append(f"  {day} ({len(sigs)} signals): {'; '.join(samples[:5])}")

        return "\n".join(lines)

    def _load_history(self) -> None:
        """Load recent signal history from disk on startup."""
        if not self._signal_log_path.exists():
            return
        try:
            with open(self._signal_log_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        sig = Signal(
                            source=d["source"],
                            sender=d["sender"],
                            text=d["text"],
                            timestamp=datetime.fromisoformat(d["timestamp"]),
                            id_key=d["id_key"],
                        )
                        self.recent_history.append(sig)
                        self._seen_ids.add(sig.id_key)
                    except (json.JSONDecodeError, KeyError):
                        continue
            log.info("Loaded %d signals from history", len(self.recent_history))
        except Exception:
            log.exception("Failed to load signal history")

    def _persist_signal(self, sig: Signal) -> None:
        """Append a signal to the on-disk log."""
        try:
            WORK_HOME.mkdir(parents=True, exist_ok=True)
            with open(self._signal_log_path, "a") as f:
                f.write(json.dumps({
                    "source": sig.source,
                    "sender": sig.sender,
                    "text": sig.text[:500],
                    "timestamp": sig.timestamp.isoformat(),
                    "id_key": sig.id_key,
                }) + "\n")
        except Exception:
            log.exception("Failed to persist signal")

    def get_unanalyzed_signals_from_log(self) -> tuple[str, str]:
        """Read all signals since the last analysis marker.

        Returns (signals_text, marker_to_set) where marker_to_set is the
        timestamp to write to the marker file after successful analysis.
        """
        marker_path = WORK_HOME / "last_analysis_marker"
        last_marker = ""
        if marker_path.exists():
            last_marker = marker_path.read_text().strip()

        if not self._signal_log_path.exists():
            return "", ""

        lines = []
        latest_ts = ""
        with open(self._signal_log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    ts = d.get("timestamp", "")
                    if ts > last_marker:
                        source = d.get("source", "?")
                        sender = d.get("sender", "?")
                        text = d.get("text", "")[:200]
                        # Include full ISO timestamp so the model can reason about timing
                        lines.append(f"[{ts}] [{source}] {sender}: {text}")
                        latest_ts = ts
                except json.JSONDecodeError:
                    continue

        # If too many signals, keep the most recent 200 but include a summary of older ones
        if len(lines) > 200:
            older = lines[:-200]
            recent = lines[-200:]

            # Compress older signals into a summary
            older_summary = f"({len(older)} older signals omitted — earliest: {older[0][:25]})"
            lines = [older_summary] + recent

        return "\n".join(lines), latest_ts

    def save_analysis_marker(self, marker: str) -> None:
        """Save the analysis marker timestamp."""
        marker_path = WORK_HOME / "last_analysis_marker"
        marker_path.write_text(marker)

    def get_recent_signals_from_log(self, minutes: int = 5) -> str:
        """Read signal_log.jsonl and return all signals from the last N minutes as formatted text."""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(minutes=minutes)
        lines: list[str] = []
        if not self._signal_log_path.exists():
            return ""
        try:
            with open(self._signal_log_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        ts = datetime.fromisoformat(d["timestamp"])
                        if ts >= cutoff:
                            hm = ts.strftime("%H:%M")
                            lines.append(f"[{hm}] [{d['source']}] {d['sender']}: {d['text']}")
                    except (json.JSONDecodeError, KeyError, ValueError):
                        continue
        except Exception:
            log.exception("Failed to read signal log for recent signals")
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
