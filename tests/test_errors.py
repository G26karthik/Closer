import pytest

from agent.errors import EmailValidationError


def test_is_exception_subclass():
    assert issubclass(EmailValidationError, Exception)


def test_preserves_message():
    msg = "subject missing deadline '2026-06-30T23:59:00Z' — retrying"
    assert str(EmailValidationError(msg)) == msg


def test_raises_and_is_catchable():
    with pytest.raises(EmailValidationError, match="retrying"):
        raise EmailValidationError("deadline missing — retrying")
