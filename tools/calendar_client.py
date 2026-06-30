from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from logger import get_logger

log = get_logger(__name__)

_PRIMARY_CALENDAR = "primary"


def _calendar_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def create_event(access_token: str, summary: str, description: str, start_iso: str, end_iso: str) -> str:
    service = _calendar_service(access_token)
    event_body = {
        "summary": summary, "description": description,
        "start": {"dateTime": start_iso, "timeZone": "UTC"},
        "end": {"dateTime": end_iso, "timeZone": "UTC"},
        "reminders": {"useDefault": True},
    }
    try:
        result = service.events().insert(calendarId=_PRIMARY_CALENDAR, body=event_body).execute()
    except HttpError as exc:
        log.error("calendar.create_failed", summary=summary, error=str(exc))
        raise
    return result["id"]
