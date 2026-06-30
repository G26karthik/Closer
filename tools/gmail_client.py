import base64
import email.mime.text

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from logger import get_logger

log = get_logger(__name__)


def _gmail_service(access_token: str):
    creds = Credentials(token=access_token)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _raw_msg(to: str, subject: str, body: str) -> str:
    msg = email.mime.text.MIMEText(body)
    msg["to"] = to
    msg["subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send_email(access_token: str, to: str, subject: str, body: str) -> str:
    service = _gmail_service(access_token)
    try:
        result = service.users().messages().send(
            userId="me", body={"raw": _raw_msg(to, subject, body)}
        ).execute()
    except HttpError as exc:
        log.error("gmail.send_failed", to=to, error=str(exc))
        raise
    return result["id"]


def create_draft(access_token: str, to: str, subject: str, body: str) -> str:
    service = _gmail_service(access_token)
    try:
        result = service.users().drafts().create(
            userId="me", body={"message": {"raw": _raw_msg(to, subject, body)}}
        ).execute()
    except HttpError as exc:
        log.error("gmail.draft_failed", to=to, error=str(exc))
        raise
    return result["id"]
