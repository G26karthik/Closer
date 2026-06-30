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


def test_find_free_slot_handles_overlapping_busy_windows():
    earliest = datetime(2026, 7, 5, 6, 0, tzinfo=timezone.utc)
    latest = datetime(2026, 7, 5, 20, 0, tzinfo=timezone.utc)
    fake_service = MagicMock()
    fake_service.freebusy().query().execute.return_value = {"calendars": {"primary": {"busy": [
        {"start": datetime(2026, 7, 5, 16, 0, tzinfo=timezone.utc).isoformat(),
         "end": datetime(2026, 7, 5, 17, 0, tzinfo=timezone.utc).isoformat()},
        {"start": datetime(2026, 7, 5, 10, 0, tzinfo=timezone.utc).isoformat(),
         "end": datetime(2026, 7, 5, 19, 0, tzinfo=timezone.utc).isoformat()},
    ]}}}
    with patch("tools.calendar_client._calendar_service", return_value=fake_service):
        start, end = find_free_slot("tok", earliest, latest, duration_hours=3)
    # Busy merges to 10:00-19:00 (16-17 nested); only free 3h gap is 06-10 → 07-10.
    assert (start, end) == (
        datetime(2026, 7, 5, 7, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 5, 10, 0, tzinfo=timezone.utc),
    )
    # The returned slot must NOT overlap the merged busy block.
    assert end <= datetime(2026, 7, 5, 10, 0, tzinfo=timezone.utc)


def test_find_free_slot_partial_busy_returns_gap_closest_to_latest():
    earliest = datetime(2026, 7, 5, 6, 0, tzinfo=timezone.utc)
    latest = datetime(2026, 7, 5, 20, 0, tzinfo=timezone.utc)
    fake_service = MagicMock()
    fake_service.freebusy().query().execute.return_value = {"calendars": {"primary": {"busy": [
        {"start": datetime(2026, 7, 5, 10, 0, tzinfo=timezone.utc).isoformat(),
         "end": datetime(2026, 7, 5, 16, 0, tzinfo=timezone.utc).isoformat()},
    ]}}}
    with patch("tools.calendar_client._calendar_service", return_value=fake_service):
        start, end = find_free_slot("tok", earliest, latest, duration_hours=2)
    # Free 06-10 and 16-20; closest-to-latest 2h slot = 18-20.
    assert (start, end) == (
        datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 5, 20, 0, tzinfo=timezone.utc),
    )


def test_find_free_slot_skips_malformed_busy_entries():
    earliest = datetime(2026, 7, 5, 8, 0, tzinfo=timezone.utc)
    latest = datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc)
    fake_service = MagicMock()
    fake_service.freebusy().query().execute.return_value = {"calendars": {"primary": {"busy": [
        {"start": "not-a-date", "end": "also-bad"},
        {"foo": "bar"},
    ]}}}
    with patch("tools.calendar_client._calendar_service", return_value=fake_service):
        start, end = find_free_slot("tok", earliest, latest, duration_hours=2)
    # Malformed entries skipped → treated as no busy → slot closest to latest = 16-18.
    assert (start, end) == (
        datetime(2026, 7, 5, 16, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 5, 18, 0, tzinfo=timezone.utc),
    )
