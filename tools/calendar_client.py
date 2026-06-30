"""
@file calendar_client.py
@description Google Calendar API client for creating events.
@module closer.tools.calendar_client
"""
from datetime import datetime, timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from logger import get_logger

log = get_logger(__name__)

# Target the user's primary calendar. If multi-calendar support is needed,
# expose calendarId as a parameter and store it in CloserState.
_PRIMARY_CALENDAR = "primary"


def _calendar_service(access_token: str):
    """Build an authenticated Google Calendar API service client.

    @param access_token: Short-lived OAuth token with calendar.events scope.
    @returns: Calendar API resource object.
    """
    creds = Credentials(token=access_token)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def create_event(
    access_token: str,
    summary: str,
    description: str,
    start_iso: str,
    end_iso: str,
) -> str:
    """Create a Google Calendar event in the user's primary calendar.

    @param access_token: OAuth token with calendar.events scope.
    @param summary: Event title shown in the calendar view.
    @param description: Longer event description.
    @param start_iso: ISO 8601 event start datetime with timezone offset.
    @param end_iso: ISO 8601 event end datetime with timezone offset.
    @returns: Google Calendar event ID.
    @throws: HttpError if the Calendar API call fails.
    """
    service = _calendar_service(access_token)
    event_body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": "UTC"},
        "end": {"dateTime": end_iso, "timeZone": "UTC"},
        "reminders": {"useDefault": True},
    }
    try:
        result = service.events().insert(
            calendarId=_PRIMARY_CALENDAR, body=event_body
        ).execute()
    except HttpError as exc:
        log.error("calendar.create_failed", summary=summary, status=exc.status_code, error=str(exc))
        raise
    log.info("calendar.event_created", event_id=result["id"], summary=summary)
    return result["id"]


def find_free_slot(
    access_token: str,
    earliest: datetime,
    latest: datetime,
    duration_hours: int,
) -> tuple[datetime, datetime]:
    """Find a free window of duration_hours within [earliest, latest], preferring
    the slot closest to `latest` (i.e. closest to the deadline).

    Overlapping/nested busy windows from the freebusy API are merged into disjoint
    intervals before scanning, so the returned slot never overlaps a busy block.
    Falls back to (latest - duration_hours, latest) if the API call fails or no
    free window of the requested size exists — callers always get a usable slot,
    never an exception.

    @param access_token: OAuth token with calendar.freebusy scope.
    @param earliest: Earliest acceptable start time.
    @param latest: Latest acceptable end time (typically the deadline).
    @param duration_hours: Required block length.
    @returns: (start, end) datetimes for the chosen slot.
    """
    duration = timedelta(hours=duration_hours)
    fallback = (latest - duration, latest)
    try:
        service = _calendar_service(access_token)
        result = service.freebusy().query(body={
            "timeMin": earliest.isoformat(),
            "timeMax": latest.isoformat(),
            "items": [{"id": _PRIMARY_CALENDAR}],
        }).execute()
        busy_raw = result.get("calendars", {}).get(_PRIMARY_CALENDAR, {}).get("busy", [])
    except HttpError as exc:
        log.warning("calendar.freebusy_failed", error=str(exc))
        return fallback

    # Parse busy entries defensively — a malformed entry must not raise.
    intervals: list[tuple[datetime, datetime]] = []
    for b in busy_raw:
        try:
            intervals.append((
                datetime.fromisoformat(b["start"]),
                datetime.fromisoformat(b["end"]),
            ))
        except (KeyError, ValueError, TypeError):
            log.warning("calendar.freebusy_malformed_entry", entry=str(b))
            continue

    # Merge overlapping/adjacent busy intervals into disjoint, sorted intervals.
    intervals.sort()
    merged: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    # Scan from `latest` backward; return the free window of `duration` closest
    # to `latest`. candidate_end walks left past each intruding busy block.
    candidate_end = latest
    for busy_start, busy_end in reversed(merged):
        if candidate_end - duration >= busy_end:
            # Gap between busy_end and candidate_end is large enough.
            if candidate_end - duration >= earliest:
                return (candidate_end - duration, candidate_end)
            return fallback
        candidate_end = min(candidate_end, busy_start)
    if candidate_end - duration >= earliest:
        return (candidate_end - duration, candidate_end)
    return fallback
