from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from tools.calendar_client import find_free_slot


def test_find_free_slot_returns_fallback_when_fully_busy():
    earliest = datetime(2026, 7, 5, 8, 0, tzinfo=timezone.utc)
    latest = datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc)
    fake_service = MagicMock()
    fake_service.freebusy().query().execute.return_value = {
        "calendars": {"primary": {"busy": [
            {"start": earliest.isoformat(), "end": latest.isoformat()},
        ]}}
    }
    with patch("tools.calendar_client._calendar_service", return_value=fake_service):
        start, end = find_free_slot("fake-token", earliest, latest, duration_hours=2)
    assert end == latest
    assert (end - start) == timedelta(hours=2)


def test_find_free_slot_finds_open_window():
    earliest = datetime(2026, 7, 5, 8, 0, tzinfo=timezone.utc)
    latest = datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc)
    fake_service = MagicMock()
    fake_service.freebusy().query().execute.return_value = {"calendars": {"primary": {"busy": []}}}
    with patch("tools.calendar_client._calendar_service", return_value=fake_service):
        start, end = find_free_slot("fake-token", earliest, latest, duration_hours=2)
    assert end == latest
    assert start == latest - timedelta(hours=2)
