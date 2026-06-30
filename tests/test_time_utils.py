"""
@file test_time_utils.py
@description Unit tests for tools/time_utils.py's parse_deadline().
@module tests.test_time_utils
"""
from datetime import datetime, timezone

from tools.time_utils import parse_deadline


def test_parse_deadline_with_z_suffix_is_aware():
    dt = parse_deadline("2026-06-30T23:59:00Z")
    assert dt.tzinfo is not None
    assert dt == datetime(2026, 6, 30, 23, 59, 0, tzinfo=timezone.utc)


def test_parse_deadline_with_explicit_offset_is_aware():
    dt = parse_deadline("2026-06-30T23:59:00+00:00")
    assert dt.tzinfo is not None


def test_parse_deadline_without_offset_is_normalized_to_utc():
    """Regression test: offset-less ISO strings used to parse as naive
    datetimes, which crashed comparisons/sorts against aware datetimes
    elsewhere in the codebase. They must now be assumed UTC.
    """
    dt = parse_deadline("2026-07-05T10:00:00")
    assert dt.tzinfo is not None
    assert dt == datetime(2026, 7, 5, 10, 0, 0, tzinfo=timezone.utc)


def test_parse_deadline_returns_none_for_non_string():
    assert parse_deadline(None) is None
    assert parse_deadline(12345) is None


def test_parse_deadline_returns_none_for_malformed_string():
    assert parse_deadline("not-a-real-date") is None
