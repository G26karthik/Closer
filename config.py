import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            "Add it to .env for local dev or to the Cloud Run service config."
        )
    return value


class _Config:
    GEMINI_API_KEY: str = _require("GEMINI_API_KEY")
    FIRESTORE_PROJECT_ID: str = _require("FIRESTORE_PROJECT_ID")

    GOOGLE_CLIENT_ID: str = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    FIREBASE_API_KEY: str = os.environ.get("FIREBASE_API_KEY", "")
    FIREBASE_AUTH_DOMAIN: str = os.environ.get("FIREBASE_AUTH_DOMAIN", "")
    CLOUD_RUN_SERVICE_URL: str = os.environ.get("CLOUD_RUN_SERVICE_URL", "")

    PORT: int = int(os.environ.get("PORT", "8080"))


cfg = _Config()
