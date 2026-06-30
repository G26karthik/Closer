from unittest.mock import MagicMock, patch

from tools.docs_client import create_document


def test_create_document_calls_create_then_batch_update():
    fake_service = MagicMock()
    fake_service.documents().create().execute.return_value = {"documentId": "doc-123"}
    with patch("tools.docs_client._docs_service", return_value=fake_service):
        doc_id = create_document("fake-token", "My Title", "Body text")
    assert doc_id == "doc-123"
    fake_service.documents().batchUpdate.assert_called()
