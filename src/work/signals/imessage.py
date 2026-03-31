"""Collect recent iMessages from chat.db."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timedelta

from work.config import IMESSAGE_DB
from work.signals.types import Signal

log = logging.getLogger(__name__)


def collect_imessages(since_minutes: int = 5, limit: int = 20) -> list[Signal]:
    """Read recent iMessages from ~/Library/Messages/chat.db."""
    results: list[Signal] = []
    try:
        if not IMESSAGE_DB.exists():
            return results
        conn = sqlite3.connect(str(IMESSAGE_DB))
        conn.row_factory = sqlite3.Row
        cutoff_unix = (datetime.now() - timedelta(minutes=since_minutes)).timestamp()
        # Apple's epoch is 2001-01-01; chat.db stores date in nanoseconds
        cutoff_apple_ns = int((cutoff_unix - 978307200) * 1_000_000_000)
        rows = conn.execute(
            """
            SELECT
                m.ROWID,
                m.text,
                datetime(m.date/1000000000 + 978307200, 'unixepoch', 'localtime') as dt,
                CASE WHEN m.is_from_me = 1 THEN 'me' ELSE
                    COALESCE(h.id, 'unknown')
                END as sender
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.text IS NOT NULL AND m.text != '' AND m.date > ?
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (cutoff_apple_ns, limit),
        ).fetchall()
        conn.close()
        for r in rows:
            sender = "You" if r["sender"] == "me" else r["sender"]
            text = (r["text"] or "")[:500]
            text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
            id_key = f"imsg-{sender}-{r['dt']}-{text_hash}"
            try:
                ts = datetime.strptime(r["dt"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                ts = datetime.now()
            results.append(
                Signal(
                    source="imessage",
                    sender=sender,
                    text=text,
                    timestamp=ts,
                    id_key=id_key,
                )
            )
    except Exception:
        log.exception("iMessage collection failed")
    return results
