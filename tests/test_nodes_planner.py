from agent.nodes import _build_subtasks_from_parsed, _find_subtask, _MAX_SUBTASKS, _SUBTASK_TYPES


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


def test_build_subtasks_drops_invalid_types():
    parsed = [{"type": "bogus", "title": "x"}, {"type": "communicate", "title": "y"}]
    result = _build_subtasks_from_parsed(parsed)
    assert len(result) == 1
    assert result[0]["id"] == "communicate_0"


def test_build_subtasks_increments_ids_per_type():
    parsed = [{"type": "communicate", "title": "a"}, {"type": "communicate", "title": "b"}]
    result = _build_subtasks_from_parsed(parsed)
    ids = [item["id"] for item in result]
    assert ids == ["communicate_0", "communicate_1"]


def test_build_subtasks_decision_deduped_to_one():
    parsed = [{"type": "decision", "title": "a"}, {"type": "decision", "title": "b"}]
    result = _build_subtasks_from_parsed(parsed)
    assert len(result) == 1
    assert result[0]["id"] == "decision_0"
    assert result[0]["needsHuman"] is True


def test_build_subtasks_caps_at_max():
    parsed = [{"type": "research", "title": f"r{i}"} for i in range(10)]
    result = _build_subtasks_from_parsed(parsed)
    assert len(result) == _MAX_SUBTASKS == 6


def test_build_subtasks_needshuman_only_for_decision():
    parsed = [{"type": "communicate", "title": "a"}, {"type": "decision", "title": "b"}]
    result = _build_subtasks_from_parsed(parsed)
    communicate = next(item for item in result if item["type"] == "communicate")
    decision = next(item for item in result if item["type"] == "decision")
    assert communicate["needsHuman"] is False
    assert decision["needsHuman"] is True


def test_build_subtasks_missing_title_defaults_to_type():
    parsed = [{"type": "schedule"}]
    result = _build_subtasks_from_parsed(parsed)
    assert result[0]["title"] == "schedule"


def test_build_subtasks_empty_when_all_invalid():
    parsed = [{"type": "bogus", "title": "x"}, {"type": "also_bogus", "title": "y"}]
    assert _build_subtasks_from_parsed(parsed) == []
