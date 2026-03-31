"""Collect open Chrome tabs via AppleScript, marking the active tab."""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime

from work.signals.types import Signal

log = logging.getLogger(__name__)

_APPLESCRIPT = '''
tell application "Google Chrome"
    set tabList to {}
    set activeWindowIndex to 0
    set activeTabIndex to 0
    try
        set activeWindowIndex to index of front window
        set activeTabIndex to active tab index of front window
    end try
    set winIndex to 0
    repeat with w in every window
        set winIndex to winIndex + 1
        set tabIndex to 0
        repeat with t in every tab of w
            set tabIndex to tabIndex + 1
            set isActive to "0"
            if winIndex = activeWindowIndex and tabIndex = activeTabIndex then
                set isActive to "1"
            end if
            set end of tabList to isActive & " ||| " & (title of t) & " ||| " & (URL of t)
        end repeat
    end repeat
    set AppleScript's text item delimiters to "\\n"
    return tabList as text
end tell
'''


def collect_chrome_tabs() -> list[Signal]:
    """Get open Chrome tab titles and URLs via osascript, with active tab marked."""
    results: list[Signal] = []
    try:
        r = subprocess.run(
            ["osascript", "-e", _APPLESCRIPT],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return results
        now = datetime.now()
        for line in r.stdout.strip().split("\n"):
            parts = line.split(" ||| ")
            if len(parts) < 3:
                continue
            is_active = parts[0].strip() == "1"
            title = parts[1].strip()
            url = parts[2].strip()
            id_key = url or title
            label = f"[ACTIVE] {title}" if is_active else title
            results.append(
                Signal(
                    source="chrome",
                    sender=url,
                    text=label[:500],
                    timestamp=now,
                    id_key=id_key,
                )
            )
    except Exception:
        log.exception("Chrome tab collection failed")
    return results
