import pytest
from agent.nodes import _find_subtask, _SUBTASK_TYPES


def test_find_subtask_returns_match():
    subtasks = [
        {"id": "communicate_0", "type": "communicate", "title": "x", "needsHuman": False},
        {"id": "decision_1", "type": "decision", "title": "y", "needsHuman": True},
    ]
    result = _find_subtask(subtasks, "communicate")
    assert result["id"] == "communicate_0"


def test_find_subtask_returns_none_when_absent():
    subtasks = [{"id": "decision_0", "type": "decision", "title": "y", "needsHuman": True}]
    assert _find_subtask(subtasks, "research") is None


def test_subtask_types_enum_has_no_none_needed_entry():
    # "none_needed" is represented by absence, not a literal type value.
    assert "none_needed" not in _SUBTASK_TYPES
