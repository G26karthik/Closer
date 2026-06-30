"""
@file config.py
@description Startup-time validation and centralisation of environment variables.
             Import `cfg` everywhere instead of calling os.environ directly.
@module closer.config
"""
import os

from dotenv import load_dotenv

# Load .env for local development. No-op when vars are already set (Cloud Run, CI).
load_dotenv()


def _require(name: str) -> str:
    """Return the value of a required environment variable or raise at startup.

    @param name: Environment variable name.
    @returns: Non-empty string value.
    @throws: RuntimeError if the variable is missing or empty.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            "Add it to .env for local dev or to the Cloud Run service config."
        )
    return value


class _Config:
    """Typed, validated application configuration.

    Attributes are read once at import time so misconfiguration fails fast
    rather than at the first request.
    """

    GEMINI_API_KEY: str = _require("GEMINI_API_KEY")
    FIRESTORE_PROJECT_ID: str = _require("FIRESTORE_PROJECT_ID")

    # Optional — empty string is a valid default for frontend injection.
    GOOGLE_CLIENT_ID: str = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    FIREBASE_API_KEY: str = os.environ.get("FIREBASE_API_KEY", "")
    FIREBASE_AUTH_DOMAIN: str = os.environ.get("FIREBASE_AUTH_DOMAIN", "")
    # SEE: injected into HTML in api.py — keep this value trusted/internal.
    CLOUD_RUN_SERVICE_URL: str = os.environ.get("CLOUD_RUN_SERVICE_URL", "")

    PORT: int = int(os.environ.get("PORT", "8080"))


cfg = _Config()
