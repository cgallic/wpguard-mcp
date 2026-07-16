"""Unit tests for wpguard_mcp.auth: bearer-token check, fail-closed behavior."""
from __future__ import annotations

import pytest

from wpguard_mcp.auth import AuthError, check_bearer_token, get_expected_token


def test_get_expected_token_raises_when_unset(monkeypatch):
    monkeypatch.delenv("WPGUARD_MCP_TOKEN", raising=False)

    with pytest.raises(AuthError):
        get_expected_token()


def test_check_bearer_token_accepts_matching_token(monkeypatch):
    monkeypatch.setenv("WPGUARD_MCP_TOKEN", "secret-token")

    assert check_bearer_token("Bearer secret-token") is True


def test_check_bearer_token_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("WPGUARD_MCP_TOKEN", "secret-token")

    assert check_bearer_token("Bearer wrong-token") is False


def test_check_bearer_token_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("WPGUARD_MCP_TOKEN", "secret-token")

    assert check_bearer_token(None) is False


def test_check_bearer_token_rejects_non_bearer_header(monkeypatch):
    monkeypatch.setenv("WPGUARD_MCP_TOKEN", "secret-token")

    assert check_bearer_token("Basic secret-token") is False


def test_check_bearer_token_raises_when_server_misconfigured(monkeypatch):
    monkeypatch.delenv("WPGUARD_MCP_TOKEN", raising=False)

    with pytest.raises(AuthError):
        check_bearer_token("Bearer anything")
