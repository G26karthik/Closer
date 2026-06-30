from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from tools.firestore_client import log_activity


@pytest.mark.asyncio
async def test_log_activity_writes_to_subcollection():
    fake_doc_ref = MagicMock()
    fake_doc_ref.add = AsyncMock()
    fake_db = MagicMock()
    fake_db.collection.return_value.document.return_value.collection.return_value = fake_doc_ref
    with patch("tools.firestore_client._get_db", return_value=fake_db):
        await log_activity("goal-1", "PlannerAgent", "plan_complete", "2 subtasks decided")
    fake_doc_ref.add.assert_awaited_once()
    written = fake_doc_ref.add.await_args[0][0]
    assert written["actor"] == "PlannerAgent"
    assert written["decision"] == "plan_complete"
