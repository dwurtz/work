"""Collect open Chrome tabs via AppleScript, marking the active tab."""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime

from work.signals.types import Signal

log = logging.getLogger(__name__)

# Get all tabs
_ALL_TABS_SCRIPT = '''
tell application "Google Chrome"
    set tabList to {}
    repeat with w in every window
        repeat with t in every tab of w
            set end of tabList to (title of t) & " ||| " & (URL of t)
        end repeat
    end repeat
    set AppleScript's text item delimiters to "\\n"
    return tabList as text
end tell
'''

# Get active tab directly
_ACTIVE_TAB_SCRIPT = '''
tell application "Google Chrome"
    return (URL of active tab of front window)
end tell
'''


def collect_chrome_tabs() -> list[Signal]:
    """Get open Chrome tab titles and URLs via osascript, with active tab marked."""
    results: list[Signal] = []
    try:
        # Get active tab URL first
        active_url = ""
        try:
            r_active = subprocess.run(
                ["osascript", "-e", _ACTIVE_TAB_SCRIPT],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r_active.returncode == 0:
                active_url = r_active.stdout.strip()
        except Exception:
            pass

        # Get all tabs
        r = subprocess.run(
            ["osascript", "-e", _ALL_TABS_SCRIPT],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return results

        now = datetime.now()
        for line in r.stdout.strip().split("\n"):
            parts = line.split(" ||| ", 1)
            title = parts[0].strip()
            url = parts[1].strip() if len(parts) > 1 else ""
            id_key = url or title
            is_active = url == active_url and active_url != ""
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
