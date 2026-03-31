"""Capture a screenshot if the screen has changed."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from datetime import datetime

from work.signals.types import Signal

log = logging.getLogger(__name__)

# Module-level state for perceptual hash diffing
_last_screen_hash = None


def capture_screenshot_if_changed() -> Signal | None:
    """
    Capture the screen, compare perceptual hash to previous capture.

    Returns a Signal with the temp file path in the text field if the screen
    has changed, or None if unchanged. The caller is responsible for vision
    analysis and deletion of the temp file.
    """
    global _last_screen_hash

    path = tempfile.mktemp(suffix=".png")
    try:
        subprocess.run(
            ["screencapture", "-x", "-C", path],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        log.exception("screencapture command failed")
        return None

    if not os.path.exists(path):
        return None

    # Perceptual hash -- skip if unchanged
    try:
        import imagehash
        from PIL import Image

        current_hash = imagehash.phash(Image.open(path))
        if _last_screen_hash is not None and current_hash - _last_screen_hash < 5:
            os.remove(path)
            return None
        _last_screen_hash = current_hash
    except ImportError:
        log.warning("imagehash/Pillow not installed; skipping perceptual hash")
    except Exception:
        log.exception("Perceptual hash comparison failed")
        # proceed even if hashing fails

    return Signal(
        source="screenshot",
        sender="screen",
        text=path,
        timestamp=datetime.now(),
        id_key=f"screen-{datetime.now().strftime('%H%M%S')}",
    )
