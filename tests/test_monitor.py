from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from agent.monitor import _is_at_risk, check_and_intervene


def test_is_at_risk_true_when_deadline_close_and_not_done():
    deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    goal = {"deadline": deadline, "status": "executing"}
    assert _is_at_risk(goal) is True


def test_is_at_risk_false_when_deadline_far():
    deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    goal = {"deadline": deadline, "status": "executing"}
    assert _is_at_risk(goal) is False


def test_is_at_risk_false_when_deadline_is_none():
    goal = {"deadline": None, "status": "executing"}
    assert _is_at_risk(goal) is False


def test_is_at_risk_false_when_deadline_is_non_string():
    goal = {"deadline": datetime.now(timezone.utc), "status": "executing"}
    assert _is_at_risk(goal) is False


def test_is_at_risk_false_when_status_done_even_if_deadline_close():
    deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    goal = {"deadline": deadline, "status": "done"}
    assert _is_at_risk(goal) is False


@pytest.mark.asyncio
async def test_check_and_intervene_skips_when_checked_recently():
    now = datetime.now(timezone.utc)
    goal = {
        "deadline": (now + timedelta(hours=1)).isoformat(),
        "status": "executing",
        "text": "Ship it",
        "lastMonitorCheck": (now - timedelta(minutes=5)).isoformat(),
    }
    with patch("agent.monitor._gemini.aio.models.generate_content", new_callable=AsyncMock) as mock_gemini, \
         patch("agent.monitor.fs.update_goal", new_callable=AsyncMock), \
         patch("agent.monitor.fs.log_activity", new_callable=AsyncMock) as mock_log:
        await check_and_intervene("goal-1", goal)
    mock_gemini.assert_not_called()
    mock_log.assert_not_called()


@pytest.mark.asyncio
async def test_check_and_intervene_proceeds_when_last_check_stale():
    now = datetime.now(timezone.utc)
    goal = {
        "deadline": (now + timedelta(hours=1)).isoformat(),
        "status": "executing",
        "text": "Ship it",
        "lastMonitorCheck": (now - timedelta(minutes=60)).isoformat(),
    }
    mock_resp = AsyncMock()
    mock_resp.text = "Send an escalation reminder now."
    with patch("agent.monitor._gemini.aio.models.generate_content", return_value=mock_resp) as mock_gemini, \
         patch("agent.monitor.fs.update_goal", new_callable=AsyncMock), \
         patch("agent.monitor.fs.log_activity", new_callable=AsyncMock) as mock_log:
        await check_and_intervene("goal-1", goal)
    mock_gemini.assert_called_once()
    mock_log.assert_awaited_once()
