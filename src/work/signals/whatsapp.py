"""Collect recent WhatsApp messages from ChatStorage.sqlite."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timedelta

from work.config import WHATSAPP_DB
from work.signals.types import Signal

log = logging.getLogger(__name__)


def collect_whatsapp(since_minutes: int = 5, limit: int = 20) -> list[Signal]:
    """Read recent WhatsApp messages from ChatStorage.sqlite."""
    results: list[Signal] = []
    try:
        if not WHATSAPP_DB.exists():
            return results
        conn = sqlite3.connect(str(WHATSAPP_DB))
        conn.row_factory = sqlite3.Row
        cutoff_unix = (datetime.now() - timedelta(minutes=since_minutes)).timestamp()
        # WhatsApp stores ZMESSAGEDATE as seconds since Apple epoch (2001-01-01)
        cutoff_apple = cutoff_unix - 978307200
        rows = conn.execute(
            """
            SELECT
                m.Z_PK,
                m.ZTEXT as text,
                datetime(m.ZMESSAGEDATE + 978307200, 'unixepoch', 'localtime') as dt,
                CASE WHEN m.ZISFROMME = 1 THEN 'me' ELSE
                    COALESCE(s.ZCONTACTJID, 'unknown')
                END as sender
            FROM ZWAMESSAGE m
            LEFT JOIN ZWACHATSESSION s ON m.ZCHATSESSION = s.Z_PK
            WHERE m.ZTEXT IS NOT NULL AND m.ZTEXT != '' AND m.ZMESSAGEDATE > ?
            ORDER BY m.ZMESSAGEDATE DESC
            LIMIT ?
            """,
            (cutoff_apple, limit),
        ).fetchall()
        conn.close()
        for r in rows:
            sender = "You" if r["sender"] == "me" else r["sender"]
            text = (r["text"] or "")[:500]
            text_hash = hashlib.md5(text.encode()).hexdigest()[:12]
            id_key = f"wa-{sender}-{r['dt']}-{text_hash}"
            try:
                ts = datetime.strptime(r["dt"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                ts = datetime.now()
            results.append(
                Signal(
                    source="whatsapp",
                    sender=sender,
                    text=text,
                    timestamp=ts,
                    id_key=id_key,
                )
            )
    except Exception:
        log.exception("WhatsApp collection failed")
    return results
