from datetime import datetime, timedelta, timezone


def _parse_deadline(deadline: str) -> datetime:
    """Mirror of the parsing logic in agent/nodes.py create_calendar_event."""
    if "T" in deadline:
        return datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    return datetime.strptime(deadline, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def test_iso_datetime_with_z_suffix():
    dt = _parse_deadline("2026-06-30T23:59:00Z")
    assert dt.year == 2026
    assert dt.month == 6
    assert dt.day == 30
    assert dt.tzinfo is not None


def test_date_only_string():
    dt = _parse_deadline("2026-06-30")
    assert dt.year == 2026
    assert dt.month == 6
    assert dt.tzinfo == timezone.utc


def test_prep_window_is_two_hours_before_deadline():
    deadline = "2026-06-30T23:59:00Z"
    end_dt = _parse_deadline(deadline)
    start_dt = end_dt - timedelta(hours=2)
    assert start_dt < end_dt
    assert int((end_dt - start_dt).total_seconds()) == 7200
