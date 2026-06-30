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
