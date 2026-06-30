import os

# Set required env vars at module level so config.py doesn't raise
# RuntimeError during pytest collection (before any fixture runs).
os.environ.setdefault("GEMINI_API_KEY", "ci-test-fake-key")
os.environ.setdefault("FIRESTORE_PROJECT_ID", "ci-test-project")
