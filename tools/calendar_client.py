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

    Falls back to (latest - duration_hours, latest) if the API call fails or no
    free window of the requested size exists in range — callers always get a
    usable slot, never an exception, matching the existing deadline-parse
    fallback pattern in agent/nodes.py.

    @param access_token: OAuth token with calendar.freebusy scope.
    @param earliest: Earliest acceptable start time.
    @param latest: Latest acceptable end time (typically the deadline).
    @param duration_hours: Required block length.
    @returns: (start, end) datetimes for the chosen slot.
    """
    fallback = (latest - timedelta(hours=duration_hours), latest)
    try:
        service = _calendar_service(access_token)
        result = service.freebusy().query(body={
            "timeMin": earliest.isoformat(),
            "timeMax": latest.isoformat(),
            "items": [{"id": _PRIMARY_CALENDAR}],
        }).execute()
        busy = result.get("calendars", {}).get(_PRIMARY_CALENDAR, {}).get("busy", [])
    except HttpError as exc:
        log.warning("calendar.freebusy_failed", error=str(exc))
        return fallback

    busy_windows = sorted(
        (datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
        for b in busy
    )
    candidate_end = latest
    for busy_start, busy_end in reversed(busy_windows):
        if candidate_end <= busy_start:
            continue
        if candidate_end - timedelta(hours=duration_hours) >= busy_end:
            return (candidate_end - timedelta(hours=duration_hours), candidate_end)
        candidate_end = min(candidate_end, busy_start)
    if candidate_end - timedelta(hours=duration_hours) >= earliest:
        return (candidate_end - timedelta(hours=duration_hours), candidate_end)
    return fallback
