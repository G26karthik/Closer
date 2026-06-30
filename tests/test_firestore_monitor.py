"""
@file test_firestore_monitor.py
@description Tests for priority ordering in list_active_goals_for_monitor().
@module tests.test_firestore_monitor
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from tools.firestore_client import list_active_goals_for_monitor


def _make_fake_doc(doc_id: str, data: dict) -> MagicMock:
    doc = MagicMock()
    doc.id = doc_id
    doc.to_dict.return_value = data
    return doc


async def _async_iter(items):
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_goals_sorted_by_ascending_time_to_deadline():
    now = datetime.now(timezone.utc)
    goal_3h = _make_fake_doc(
        "goal-3h", {"deadline": (now + timedelta(hours=3)).isoformat(), "status": "executing"}
    )
    goal_1h = _make_fake_doc(
        "goal-1h", {"deadline": (now + timedelta(hours=1)).isoformat(), "status": "executing"}
    )
    goal_24h = _make_fake_doc(
        "goal-24h", {"deadline": (now + timedelta(hours=24)).isoformat(), "status": "executing"}
    )

    fake_query = MagicMock()
    fake_query.stream.return_value = _async_iter([goal_3h, goal_1h, goal_24h])
    fake_db = MagicMock()
    fake_db.collection.return_value.where.return_value = fake_query

    with patch("tools.firestore_client._get_db", return_value=fake_db):
        result = await list_active_goals_for_monitor()

    assert [g["id"] for g in result] == ["goal-1h", "goal-3h", "goal-24h"]


@pytest.mark.asyncio
async def test_goal_with_malformed_or_missing_deadline_sorts_last():
    now = datetime.now(timezone.utc)
    goal_valid = _make_fake_doc(
        "goal-valid", {"deadline": (now + timedelta(hours=5)).isoformat(), "status": "executing"}
    )
    goal_malformed = _make_fake_doc(
        "goal-malformed", {"deadline": "not-a-real-date", "status": "executing"}
    )
    goal_missing = _make_fake_doc("goal-missing", {"status": "executing"})

    fake_query = MagicMock()
    fake_query.stream.return_value = _async_iter([goal_malformed, goal_missing, goal_valid])
    fake_db = MagicMock()
    fake_db.collection.return_value.where.return_value = fake_query

    with patch("tools.firestore_client._get_db", return_value=fake_db):
        result = await list_active_goals_for_monitor()

    assert result[0]["id"] == "goal-valid"
    assert {g["id"] for g in result[1:]} == {"goal-malformed", "goal-missing"}
