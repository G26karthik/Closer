from datetime import datetime, timedelta, timezone

from agent.monitor import _is_at_risk


def test_is_at_risk_true_when_deadline_close_and_not_done():
    deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    goal = {"deadline": deadline, "status": "executing"}
    assert _is_at_risk(goal) is True


def test_is_at_risk_false_when_deadline_far():
    deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    goal = {"deadline": deadline, "status": "executing"}
    assert _is_at_risk(goal) is False
