import json
from unittest.mock import AsyncMock, patch

import pytest

from agent.errors import OutputQualityError
from agent.nodes import _evaluate_output


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
