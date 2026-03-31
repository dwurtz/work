"""Simple scope detection from user messages."""

from __future__ import annotations


def detect_scope(
    message: str,
    scopes: list[tuple[str, str | None]],
) -> tuple[str, str | None] | None:
    """Try to detect which scope a message relates to. Returns None if ambiguous.

    Performs simple keyword matching: checks whether any scope name appears
    in the message text (case-insensitive). Returns the first match, or None
    if zero or multiple scopes match.
    """
    msg_lower = message.lower()
    hits: list[tuple[str, str | None]] = []

    for scope_type, name in scopes:
        # Check for the scope name in the message
        if name and name.lower() in msg_lower:
            hits.append((scope_type, name))
        elif not name and scope_type.lower() in msg_lower:
            hits.append((scope_type, name))

    # Only return if exactly one scope matched
    if len(hits) == 1:
        return hits[0]

    return None
