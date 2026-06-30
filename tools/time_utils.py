"""
@file time_utils.py
@description Shared datetime parsing helpers used by the monitor and Firestore client.
@module closer.tools.time_utils
"""
from datetime import datetime


def parse_deadline(deadline: object) -> datetime | None:
    """Parse a goal's deadline field into an aware datetime, or None if unparseable.

    @param deadline: The raw `deadline` value from a Firestore goal doc (expected
        to be an ISO 8601 string, but may be None, malformed, or a non-string type).
    @returns: Parsed datetime, or None if the value can't be parsed.
    """
    if not isinstance(deadline, str):
        return None
    try:
        return datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
