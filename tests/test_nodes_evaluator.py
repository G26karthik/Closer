import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.errors import OutputQualityError
from agent.nodes import _evaluate_output, produce_document, research_topic


@pytest.mark.asyncio
async def test_evaluate_output_accepts_good_output():
    mock_response = AsyncMock()
    mock_response.text = json.dumps({"verdict": "accept", "reason": "covers deadline"})
    with patch("agent.nodes._gemini.aio.models.generate_content", return_value=mock_response):
        await _evaluate_output("Submit report", "2026-07-05", "communicate", "Email mentions 2026-07-05 deadline.")


@pytest.mark.asyncio
async def test_evaluate_output_rejects_bad_output():
    mock_response = AsyncMock()
    mock_response.text = json.dumps({"verdict": "reject", "reason": "missing deadline"})
    with patch("agent.nodes._gemini.aio.models.generate_content", return_value=mock_response):
        with pytest.raises(OutputQualityError, match="missing deadline"):
            await _evaluate_output("Submit report", "2026-07-05", "communicate", "Generic email, no date.")


@pytest.mark.asyncio
async def test_research_topic_skips_when_not_planned():
    ctx = MagicMock()
    ctx.state = {"subtasks": [{"id": "communicate_0", "type": "communicate", "title": "x", "needsHuman": False}]}
    with patch("agent.nodes.fs.update_subtask", new_callable=AsyncMock) as mock_update:
        await research_topic(ctx, "Submit report", "2026-07-05", "goal-1")
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_produce_document_skips_when_not_planned():
    ctx = MagicMock()
    ctx.state = {"subtasks": [{"id": "communicate_0", "type": "communicate", "title": "x", "needsHuman": False}]}
    with patch("agent.nodes.fs.update_subtask", new_callable=AsyncMock) as mock_update:
        await produce_document(ctx, "Submit report", "2026-07-05", "goal-1", "fake-token")
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_research_topic_evaluates_before_marking_done():
    ctx = MagicMock()
    ctx.state = {"subtasks": [{"id": "research_0", "type": "research", "title": "x", "needsHuman": False}]}
    mock_resp = AsyncMock()
    mock_resp.text = "Relevant findings about the goal."
    calls = []
    async def track_update(goal_id, sid, data):
        calls.append(("update", data.get("status")))
    async def track_eval(goal, deadline, stype, summary):
        calls.append(("evaluate", stype))
    async def track_log(*a, **kw):
        calls.append(("log", None))
    with patch("agent.nodes._gemini.aio.models.generate_content", return_value=mock_resp), \
         patch("agent.nodes.fs.update_subtask", side_effect=track_update), \
         patch("agent.nodes._evaluate_output", side_effect=track_eval), \
         patch("agent.nodes.fs.log_activity", side_effect=track_log):
        await research_topic(ctx, "Submit report", "2026-07-05", "goal-1")
    # running update must precede evaluate, evaluate must precede done update
    assert calls[0] == ("update", "running")
    eval_idx = calls.index(("evaluate", "research"))
    done_idx = next(i for i, c in enumerate(calls) if c == ("update", "done"))
    assert eval_idx < done_idx, f"evaluate must run before marking done; got {calls}"


@pytest.mark.asyncio
async def test_research_topic_rejection_prevents_done():
    from agent.errors import OutputQualityError
    ctx = MagicMock()
    ctx.state = {"subtasks": [{"id": "research_0", "type": "research", "title": "x", "needsHuman": False}]}
    mock_resp = AsyncMock()
    mock_resp.text = "Weak findings."
    done_marked = []
    async def track_update(goal_id, sid, data):
        if data.get("status") == "done":
            done_marked.append(True)
    async def reject(goal, deadline, stype, summary):
        raise OutputQualityError("findings insufficient")
    with patch("agent.nodes._gemini.aio.models.generate_content", return_value=mock_resp), \
         patch("agent.nodes.fs.update_subtask", side_effect=track_update), \
         patch("agent.nodes._evaluate_output", side_effect=reject), \
         patch("agent.nodes.fs.log_activity", new_callable=AsyncMock):
        with pytest.raises(OutputQualityError):
            await research_topic(ctx, "Submit report", "2026-07-05", "goal-1")
    assert not done_marked, "subtask must NOT be marked done when evaluation rejects"
