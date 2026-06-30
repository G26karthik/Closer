import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.errors import OutputQualityError
from agent.nodes import _evaluate_output, research_topic


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
