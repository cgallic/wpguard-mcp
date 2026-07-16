"""Bearer-token auth for the wpguard-mcp HTTP server.

Deliberately simple and fails closed: if WPGUARD_MCP_TOKEN is unset, every
request is rejected rather than the server silently running unauthenticated.
This is a static shared-secret check, not OAuth -- appropriate for a
single-operator local/tailnet MCP server talking to your own sites.
"""
from __future__ import annotations

import hmac
import os

TOKEN_ENV_VAR = "WPGUARD_MCP_TOKEN"


class AuthError(RuntimeError):
    """Raised when the server is misconfigured (no token set)."""


def get_expected_token() -> str:
    """Read the configured bearer token from the environment.

    Raises AuthError if it isn't set -- there is no "unauthenticated" mode.
    """
    token = os.environ.get(TOKEN_ENV_VAR, "")
    if not token:
        raise AuthError(
            f"{TOKEN_ENV_VAR} is not set. wpguard-mcp refuses to start without an auth "
            f"token configured; there is no unauthenticated fallback."
        )
    return token


def check_bearer_token(header_value: str | None) -> bool:
    """Return True if `header_value` (a raw Authorization header) carries the
    expected bearer token. Uses a constant-time comparison to avoid leaking
    timing information about the token.
    """
    expected = get_expected_token()
    if not header_value or not header_value.startswith("Bearer "):
        return False
    presented = header_value[len("Bearer ") :].strip()
    return hmac.compare_digest(presented, expected)
