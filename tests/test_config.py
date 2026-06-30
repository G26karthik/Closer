import pytest

from config import _require


def test_require_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("_CLOSER_TEST_VAR", "hello")
    assert _require("_CLOSER_TEST_VAR") == "hello"


def test_require_raises_when_missing(monkeypatch):
    monkeypatch.delenv("_CLOSER_TEST_MISSING", raising=False)
    with pytest.raises(RuntimeError, match="_CLOSER_TEST_MISSING"):
        _require("_CLOSER_TEST_MISSING")


def test_require_strips_and_rejects_whitespace_only(monkeypatch):
    monkeypatch.setenv("_CLOSER_TEST_BLANK", "   ")
    with pytest.raises(RuntimeError, match="_CLOSER_TEST_BLANK"):
        _require("_CLOSER_TEST_BLANK")
