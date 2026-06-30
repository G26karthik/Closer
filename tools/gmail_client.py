"""
@file gmail_client.py
@description Gmail API client for sending messages and creating drafts.
@module closer.tools.gmail_client
"""
import base64
import email.mime.text

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from logger import get_logger

log = get_logger(__name__)


def _gmail_service(access_token: str):
    """Build an authenticated Gmail API service client.

    @param access_token: Short-lived OAuth token with gmail.compose scope.
    @returns: Gmail API resource object.
    """
    creds = Credentials(token=access_token)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _raw_msg(to: str, subject: str, body: str) -> str:
    """Encode a plain-text email as base64url for the Gmail API raw send format.

    @param to: Recipient address.
    @param subject: Email subject line.
    @param body: Plain-text email body.
    @returns: Base64url-encoded RFC 2822 message string.
    """
    msg = email.mime.text.MIMEText(body)
    msg["to"] = to
    msg["subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send_email(access_token: str, to: str, subject: str, body: str) -> str:
    """Send an email immediately via the Gmail API.

    @param access_token: OAuth token with gmail.compose + gmail.send scope.
    @param to: Recipient address or 'me' for the authenticated user.
    @param subject: Email subject line.
    @param body: Plain-text email body.
    @returns: Gmail message ID of the sent message.
    @throws: HttpError if the Gmail API call fails.
    """
    service = _gmail_service(access_token)
    try:
        result = service.users().messages().send(
            userId="me", body={"raw": _raw_msg(to, subject, body)}
        ).execute()
    except HttpError as exc:
        log.error("gmail.send_failed", to=to, status=exc.status_code, error=str(exc))
        raise
    log.info("gmail.sent", to=to, msg_id=result["id"])
    return result["id"]


def create_draft(access_token: str, to: str, subject: str, body: str) -> str:
    """Create a Gmail draft without sending it.

    @param access_token: OAuth token with gmail.compose scope.
    @param to: Intended recipient address.
    @param subject: Email subject line.
    @param body: Plain-text email body.
    @returns: Gmail draft ID.
    @throws: HttpError if the Gmail API call fails.
    """
    service = _gmail_service(access_token)
    try:
        result = service.users().drafts().create(
            userId="me", body={"message": {"raw": _raw_msg(to, subject, body)}}
        ).execute()
    except HttpError as exc:
        log.error("gmail.draft_failed", to=to, status=exc.status_code, error=str(exc))
        raise
    log.info("gmail.draft_created", to=to, draft_id=result["id"])
    return result["id"]
