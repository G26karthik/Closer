from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.nodes import request_human_decision


def _ctx(subtasks, resume_inputs=None):
    ctx = MagicMock()
    ctx.state = {"subtasks": subtasks}
    ctx.resume_inputs = resume_inputs if resume_inputs is not None else {}
    return ctx


@pytest.mark.asyncio
async def test_request_human_decision_skips_when_not_planned():
    ctx = _ctx([{"id": "communicate_0", "type": "communicate", "title": "x", "needsHuman": False}])
    with patch("agent.nodes.fs.update_goal", new_callable=AsyncMock) as mock_goal, \
         patch("agent.nodes.fs.update_subtask", new_callable=AsyncMock) as mock_sub, \
         patch("agent.nodes.fs.store_hitl_interrupt", new_callable=AsyncMock) as mock_store:
        results = [x async for x in request_human_decision(ctx, "goal-1")]
    assert results == []
    mock_goal.assert_awaited_once_with("goal-1", {"status": "done"})
    mock_sub.assert_not_called()
    mock_store.assert_not_called()


@pytest.mark.asyncio
async def test_request_human_decision_first_call_surfaces_card():
    ctx = _ctx(
        [
            {"id": "communicate_0", "type": "communicate", "title": "x", "needsHuman": False},
            {"id": "decision_0", "type": "decision", "title": "Pick A or B", "needsHuman": True},
        ],
        resume_inputs={},
    )
    with patch("agent.nodes.fs.update_goal", new_callable=AsyncMock), \
         patch("agent.nodes.fs.update_subtask", new_callable=AsyncMock) as mock_sub, \
         patch("agent.nodes.fs.store_hitl_interrupt", new_callable=AsyncMock) as mock_store:
        results = [x async for x in request_human_decision(ctx, "goal-1")]
    assert len(results) == 1  # exactly one RequestInput event yielded
    mock_store.assert_awaited_once()
    mock_sub.assert_awaited_once_with(
        "goal-1", "decision_0", {"status": "needs_human", "needsHuman": True}
    )


@pytest.mark.asyncio
async def test_request_human_decision_resume_records_choice():
    ctx = _ctx(
        [
            {"id": "communicate_0", "type": "communicate", "title": "x", "needsHuman": False},
            {"id": "decision_0", "type": "decision", "title": "Pick A or B", "needsHuman": True},
        ],
        resume_inputs={"hitl_project_desc_goal-1": {"choice": "B"}},
    )
    with patch("agent.nodes.fs.update_goal", new_callable=AsyncMock) as mock_goal, \
         patch("agent.nodes.fs.update_subtask", new_callable=AsyncMock) as mock_sub, \
         patch("agent.nodes.fs.store_hitl_interrupt", new_callable=AsyncMock):
        results = [x async for x in request_human_decision(ctx, "goal-1")]
    assert results == []
    assert ctx.state["human_decision"] == "B"
    mock_goal.assert_awaited_once_with("goal-1", {"status": "done", "hitlInterruptId": None})
    # subtask marked done against the dynamic id, result mentions the choice
    assert mock_sub.await_count == 1
    call = mock_sub.await_args_list[0]
    assert call.args[0] == "goal-1"
    assert call.args[1] == "decision_0"
    assert call.args[2]["status"] == "done"
    assert "B" in call.args[2]["result"]
