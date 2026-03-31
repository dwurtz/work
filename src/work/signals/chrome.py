"""Collect open Chrome tabs via AppleScript."""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime

from work.signals.types import Signal

log = logging.getLogger(__name__)

_APPLESCRIPT = '''
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


def collect_chrome_tabs() -> list[Signal]:
    """Get open Chrome tab titles and URLs via osascript."""
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
            parts = line.split(" ||| ", 1)
            title = parts[0].strip()
            url = parts[1].strip() if len(parts) > 1 else ""
            id_key = url or title
            results.append(
                Signal(
                    source="chrome",
                    sender=url,
                    text=title[:500],
                    timestamp=now,
                    id_key=id_key,
                )
            )
    except Exception:
        log.exception("Chrome tab collection failed")
    return results
