"""Unit tests for trazo.core.redactor (TRZ-P2-03)."""

from __future__ import annotations

from trazo.core.redactor import Redactor


def test_redactor__redacts_default_sensitive_keys() -> None:
    redactor = Redactor()
    value = {"password": "hunter2", "api_key": "sk-123", "safe": "ok"}

    result = redactor.redact(value)

    assert result["password"] == "***REDACTED***"
    assert result["api_key"] == "***REDACTED***"
    assert result["safe"] == "ok"


def test_redactor__is_case_insensitive_and_substring_matched() -> None:
    redactor = Redactor()
    value = {"AUTHORIZATION": "Bearer x", "user_auth_token": "t"}

    result = redactor.redact(value)

    assert result["AUTHORIZATION"] == "***REDACTED***"
    assert result["user_auth_token"] == "***REDACTED***"


def test_redactor__does_not_false_positive_on_llm_usage_token_counts() -> None:
    """Regression: a bare "token" pattern previously caught llm.call's
    legitimate tokens_in/tokens_out fields (EVENTS.md §2.3), redacting
    real usage metrics — caught via the LangGraph adapter integration test."""
    redactor = Redactor()
    value = {"tokens_in": 128, "tokens_out": 24, "token_usage": {"a": 1}}

    result = redactor.redact(value)

    assert result["tokens_in"] == 128
    assert result["tokens_out"] == 24
    assert result["token_usage"] == {"a": 1}


def test_redactor__recurses_into_nested_dicts_and_lists() -> None:
    redactor = Redactor()
    value = {"outer": {"password": "x"}, "items": [{"secret": "y"}, {"ok": "z"}]}

    result = redactor.redact(value)

    assert result["outer"]["password"] == "***REDACTED***"
    assert result["items"][0]["secret"] == "***REDACTED***"
    assert result["items"][1]["ok"] == "z"


def test_redactor__extra_keys_are_additive_to_defaults() -> None:
    redactor = Redactor(extra_keys=["ssn"])
    value = {"ssn": "123-45-6789", "password": "still-redacted"}

    result = redactor.redact(value)

    assert result["ssn"] == "***REDACTED***"
    assert result["password"] == "***REDACTED***"


def test_redactor__leaves_non_dict_non_list_values_untouched() -> None:
    redactor = Redactor()
    assert redactor.redact(5) == 5
    assert redactor.redact("plain string") == "plain string"
    assert redactor.redact(None) is None
