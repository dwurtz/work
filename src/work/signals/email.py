"""Email signal collector using the gws CLI tool."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime

from work.signals.types import Signal

log = logging.getLogger(__name__)


# Subjects/senders to ignore (emails sent by the system itself)
_SELF_EMAIL_FILTERS = [
    "[work]",           # all system-sent emails have [work] in subject
    "david@davidwurtz.com",  # emails from self
]


def collect_recent_emails(since_minutes: int = 15) -> list[Signal]:
    """Collect unread emails from the last N minutes using gws CLI."""
    signals: list[Signal] = []

    try:
        result = subprocess.run(
            [
                "gws", "gmail", "users", "messages", "list",
                "--params", json.dumps({
                    "userId": "me",
                    "q": f"is:unread newer_than:{since_minutes}m",
                    "maxResults": 5,
                }),
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            log.warning("gws gmail list failed: %s", result.stderr[:200])
            return signals

        data = json.loads(result.stdout)
        messages = data.get("messages", [])
        if not messages:
            return signals

        for msg in messages:
            msg_id = msg.get("id")
            if not msg_id:
                continue

            try:
                detail_result = subprocess.run(
                    [
                        "gws", "gmail", "users", "messages", "get",
                        "--params", json.dumps({
                            "userId": "me",
                            "id": msg_id,
                            "format": "full",
                            "metadataHeaders": ["From", "Subject", "Date"],
                        }),
                        "--format", "json",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if detail_result.returncode != 0:
                    continue

                detail = json.loads(detail_result.stdout)

                # Extract headers from payload
                headers = {}
                for h in detail.get("payload", {}).get("headers", []):
                    if h.get("name") in ("From", "Subject", "Date"):
                        headers[h["name"]] = h["value"]

                sender = headers.get("From", "")
                subject = headers.get("Subject", "")
                snippet = detail.get("snippet", "")

                # Use subject if available, otherwise snippet
                text = subject if subject else snippet[:200]
                if not sender:
                    sender = "Unknown"

                # Skip emails sent by the system itself
                skip = False
                for filt in _SELF_EMAIL_FILTERS:
                    if filt.lower() in subject.lower() or filt.lower() in sender.lower():
                        skip = True
                        break
                if skip:
                    continue

                signals.append(Signal(
                    source="email",
                    sender=sender[:100],
                    text=text[:500],
                    timestamp=datetime.now(),
                    id_key=f"email-{msg_id}",
                ))

            except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
                log.debug("Failed to fetch email %s: %s", msg_id, e)
                continue

    except subprocess.TimeoutExpired:
        log.warning("gws gmail list timed out")
    except json.JSONDecodeError:
        log.warning("gws gmail list returned invalid JSON")
    except FileNotFoundError:
        log.warning("gws CLI not found on PATH")
    except Exception:
        log.exception("Email collector error")

    return signals
