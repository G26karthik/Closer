class EmailValidationError(Exception):
    """Raised by draft_email on attempt 1 to trigger ADK RetryConfig."""
