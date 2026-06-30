"""
@file docs_client.py
@description Google Docs API client for generating real deliverable artifacts.
@module closer.tools.docs_client
"""
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from logger import get_logger

log = get_logger(__name__)


def _docs_service(access_token: str):
    """Build an authenticated Google Docs API service client.

    @param access_token: OAuth token with documents scope.
    @returns: Docs API resource object.
    """
    creds = Credentials(token=access_token)
    return build("docs", "v1", credentials=creds, cache_discovery=False)


def create_document(access_token: str, title: str, content: str) -> str:
    """Create a Google Doc and insert content into it.

    @param access_token: OAuth token with documents scope.
    @param title: Document title.
    @param content: Plain-text body to insert at the start of the document.
    @returns: Google Docs document ID.
    @throws: HttpError if the Docs API call fails.
    """
    service = _docs_service(access_token)
    try:
        doc = service.documents().create(body={"title": title}).execute()
        document_id = doc["documentId"]
        service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
        ).execute()
    except HttpError as exc:
        log.error("docs.create_failed", title=title, status=exc.status_code, error=str(exc))
        raise
    log.info("docs.created", document_id=document_id, title=title)
    return document_id
