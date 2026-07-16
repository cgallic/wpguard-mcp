"""Token scoping (issue #7) and per-token rate limiting (issue #10).

This is the authorization layer that sits above the change-guard. The guard
answers "is there an approved reason for this write"; policy answers "is this
*caller* even allowed to reach this tier of tool, and are they calling too
fast." Both are enforced before a tool runs.

Scopes (least- to most-privileged), each a superset of the one below:

    recon   -- Tier 1 read-only tools only
    mutate  -- Tier 1 + Tier 2 guarded named verbs (+ packet lifecycle)
    admin   -- everything, including Tier 3 raw eval (wp_eval)

Tokens are configured per scope via environment variables, so you can hand a
lower-trust client (or a less-trusted AI harness) a recon- or mutate-scoped
token without giving it the keys to raw eval:

    WPGUARD_TOKEN_RECON=<one or more comma-separated tokens>
    WPGUARD_TOKEN_MUTATE=<...>
    WPGUARD_TOKEN_ADMIN=<...>

The legacy single WPGUARD_MCP_TOKEN is still honored and maps to admin scope,
so existing single-token setups keep working unchanged.

Rate limiting is a fixed-window (60s) per-token call cap, with a separate,
tighter cap on Tier 3 calls given raw eval's higher blast radius:

    WPGUARD_RATE_LIMIT_PER_MIN        (default 120)
    WPGUARD_RATE_LIMIT_TIER3_PER_MIN  (default 10)
"""
from __future__ import annotations

import hmac
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Scope name -> privilege level. A token of level N may call any tool of tier
# <= N.
SCOPE_LEVELS = {"recon": 1, "mutate": 2, "admin": 3}

# Tool name -> minimum tier required. Every tool the server registers must be
# listed; an unmapped tool is treated as Tier 3 (admin-only) so a new tool
# added without a policy entry fails closed rather than open.
TOOL_TIERS = {
    # Tier 1: read-only recon
    "wp_recon": 1,
    "wp_get_option": 1,
    "wp_get_post_meta": 1,
    "site_list": 1,
    "packet_list": 1,
    # Tier 2: guarded named verbs + the packet lifecycle that authorizes them
    "wp_mutate_option": 2,
    "wp_mutate_post_meta": 2,
    "wp_mutate_post_content": 2,
    "wp_cache_bust": 2,
    "packet_open": 2,
    "packet_approve": 2,
    "packet_log": 2,
    "packet_close": 2,
    "site_register": 2,
    # Tier 3: raw escape hatch
    "wp_eval": 3,
}

DEFAULT_TIER = 3  # fail closed for anything not explicitly mapped

LEGACY_TOKEN_ENV = "WPGUARD_MCP_TOKEN"
SCOPE_TOKEN_ENVS = {
    "recon": "WPGUARD_TOKEN_RECON",
    "mutate": "WPGUARD_TOKEN_MUTATE",
    "admin": "WPGUARD_TOKEN_ADMIN",
}

RATE_LIMIT_ENV = "WPGUARD_RATE_LIMIT_PER_MIN"
RATE_LIMIT_TIER3_ENV = "WPGUARD_RATE_LIMIT_TIER3_PER_MIN"
DEFAULT_RATE_LIMIT = 120
DEFAULT_RATE_LIMIT_TIER3 = 10


class PolicyNotConfiguredError(RuntimeError):
    """Raised when no tokens at all are configured -- the server must fail closed."""


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def load_tokens() -> dict[str, str]:
    """Return a mapping of token string -> scope, from the environment.

    If the same token is set at multiple scopes, the highest privilege wins.
    """
    tokens: dict[str, str] = {}

    def assign(token: str, scope: str) -> None:
        existing = tokens.get(token)
        if existing is None or SCOPE_LEVELS[scope] > SCOPE_LEVELS[existing]:
            tokens[token] = scope

    for scope, env_name in SCOPE_TOKEN_ENVS.items():
        for tok in _split_csv(os.environ.get(env_name, "")):
            assign(tok, scope)

    legacy = os.environ.get(LEGACY_TOKEN_ENV, "").strip()
    if legacy:
        assign(legacy, "admin")

    return tokens


def require_configured() -> None:
    """Raise unless at least one token is configured (fail-closed startup check)."""
    if not load_tokens():
        raise PolicyNotConfiguredError(
            "No wpguard tokens configured. Set WPGUARD_MCP_TOKEN (admin) or one of "
            "WPGUARD_TOKEN_RECON / WPGUARD_TOKEN_MUTATE / WPGUARD_TOKEN_ADMIN. "
            "wpguard-mcp refuses to start without an auth token; there is no "
            "unauthenticated fallback."
        )


def authenticate(authorization_header: str | None) -> str | None:
    """Return the scope for a bearer Authorization header, or None if it matches
    no configured token. Compares against every configured token (not
    short-circuiting) to avoid leaking which token, if any, was close.
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return None
    presented = authorization_header[len("Bearer ") :].strip()
    matched: str | None = None
    for token, scope in load_tokens().items():
        if hmac.compare_digest(presented, token):
            matched = scope
    return matched


def tier_for_tool(tool_name: str) -> int:
    return TOOL_TIERS.get(tool_name, DEFAULT_TIER)


def scope_allows(scope: str, tier: int) -> bool:
    return SCOPE_LEVELS.get(scope, 0) >= tier


def _rate_limit() -> int:
    try:
        return int(os.environ.get(RATE_LIMIT_ENV, "").strip() or DEFAULT_RATE_LIMIT)
    except ValueError:
        return DEFAULT_RATE_LIMIT


def _rate_limit_tier3() -> int:
    try:
        return int(os.environ.get(RATE_LIMIT_TIER3_ENV, "").strip() or DEFAULT_RATE_LIMIT_TIER3)
    except ValueError:
        return DEFAULT_RATE_LIMIT_TIER3


@dataclass
class _Window:
    started_at: float
    count: int = 0
    tier3_count: int = 0


@dataclass
class RateLimiter:
    """Fixed 60-second window per token, with a separate Tier 3 sub-count.

    `clock` is injectable so tests don't have to sleep.
    """

    clock: Callable[[], float] = time.monotonic
    window_seconds: float = 60.0
    _windows: dict[str, _Window] = field(default_factory=dict)

    def check(self, token_key: str, tier: int) -> tuple[bool, str]:
        """Record a call and report whether it's allowed.

        Returns (allowed, reason). A rejected call is NOT counted (so a client
        that backs off isn't perpetually starved by its own retries).
        """
        now = self.clock()
        window = self._windows.get(token_key)
        if window is None or (now - window.started_at) >= self.window_seconds:
            window = _Window(started_at=now)
            self._windows[token_key] = window

        overall_limit = _rate_limit()
        tier3_limit = _rate_limit_tier3()

        if tier >= 3 and window.tier3_count >= tier3_limit:
            return False, f"Tier 3 rate limit exceeded ({tier3_limit}/min for raw eval)"
        if window.count >= overall_limit:
            return False, f"rate limit exceeded ({overall_limit}/min)"

        window.count += 1
        if tier >= 3:
            window.tier3_count += 1
        return True, ""


@dataclass
class Decision:
    ok: bool
    status: int = 200
    message: str = ""
    scope: str | None = None
    tool: str | None = None


def _extract_tool_call(body: bytes) -> str | None:
    """Return the tool name if `body` is an MCP tools/call request, else None."""
    if not body:
        return None
    try:
        data: Any = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("method") != "tools/call":
        return None
    params = data.get("params")
    if isinstance(params, dict):
        name = params.get("name")
        if isinstance(name, str):
            return name
    return None


def evaluate_request(authorization_header: str | None, body: bytes, rate_limiter: RateLimiter) -> Decision:
    """Authenticate + authorize + rate-limit a single request, purely.

    Returns a Decision the transport layer turns into a response. This is where
    the token's scope is checked against the called tool's tier and the
    per-token rate limit is applied. Non-tool-call requests (initialize,
    tools/list, ...) only require a valid token.
    """
    scope = authenticate(authorization_header)
    if scope is None:
        return Decision(ok=False, status=401, message="unauthorized")

    tool = _extract_tool_call(body)
    if tool is None:
        return Decision(ok=True, scope=scope)

    tier = tier_for_tool(tool)
    if not scope_allows(scope, tier):
        return Decision(
            ok=False,
            status=403,
            message=(
                f"scope '{scope}' may not call '{tool}' (requires tier {tier}). "
                f"Use a higher-scoped token."
            ),
            scope=scope,
            tool=tool,
        )

    # scope is non-None here, so authenticate() matched a "Bearer <token>" header.
    assert authorization_header is not None
    presented = authorization_header[len("Bearer ") :].strip()
    allowed, reason = rate_limiter.check(presented, tier)
    if not allowed:
        return Decision(ok=False, status=429, message=reason, scope=scope, tool=tool)

    return Decision(ok=True, scope=scope, tool=tool)
