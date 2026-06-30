import pytest

from agent.errors import EmailValidationError, OutputQualityError


def test_is_exception_subclass():
    assert issubclass(EmailValidationError, Exception)


def test_preserves_message():
    msg = "subject missing deadline '2026-06-30T23:59:00Z' — retrying"
    assert str(EmailValidationError(msg)) == msg


def test_raises_and_is_catchable():
    with pytest.raises(EmailValidationError, match="retrying"):
        raise EmailValidationError("deadline missing — retrying")


def test_output_quality_error_is_exception():
    err = OutputQualityError("missing deadline reference")
    assert isinstance(err, Exception)
    assert str(err) == "missing deadline reference"
