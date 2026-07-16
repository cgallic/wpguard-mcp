"""Issues #7 (scoped tokens) and #10 (per-token rate limits)."""
from __future__ import annotations

import asyncio
import json

import pytest

from wpguard_mcp import policy
from wpguard_mcp.server import PolicyMiddleware


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in (
        policy.LEGACY_TOKEN_ENV,
        policy.RATE_LIMIT_ENV,
        policy.RATE_LIMIT_TIER3_ENV,
        *policy.SCOPE_TOKEN_ENVS.values(),
    ):
        monkeypatch.delenv(var, raising=False)


# --- token loading + scopes ------------------------------------------------


def test_legacy_token_maps_to_admin(monkeypatch):
    monkeypatch.setenv(policy.LEGACY_TOKEN_ENV, "legacy")
    assert policy.load_tokens() == {"legacy": "admin"}


def test_scoped_tokens_loaded(monkeypatch):
    monkeypatch.setenv(policy.SCOPE_TOKEN_ENVS["recon"], "r1, r2")
    monkeypatch.setenv(policy.SCOPE_TOKEN_ENVS["mutate"], "m1")
    tokens = policy.load_tokens()
    assert tokens == {"r1": "recon", "r2": "recon", "m1": "mutate"}


def test_highest_privilege_wins_for_shared_token(monkeypatch):
    monkeypatch.setenv(policy.SCOPE_TOKEN_ENVS["recon"], "shared")
    monkeypatch.setenv(policy.SCOPE_TOKEN_ENVS["admin"], "shared")
    assert policy.load_tokens()["shared"] == "admin"


def test_require_configured_raises_when_empty():
    with pytest.raises(policy.PolicyNotConfiguredError):
        policy.require_configured()


def test_authenticate_returns_scope(monkeypatch):
    monkeypatch.setenv(policy.SCOPE_TOKEN_ENVS["recon"], "r1")
    assert policy.authenticate("Bearer r1") == "recon"
    assert policy.authenticate("Bearer wrong") is None
    assert policy.authenticate(None) is None
    assert policy.authenticate("r1") is None  # missing Bearer prefix


def test_tier_and_scope_helpers():
    assert policy.tier_for_tool("wp_recon") == 1
    assert policy.tier_for_tool("wp_mutate_option") == 2
    assert policy.tier_for_tool("wp_eval") == 3
    assert policy.tier_for_tool("some_future_tool") == policy.DEFAULT_TIER == 3
    assert policy.scope_allows("recon", 1) is True
    assert policy.scope_allows("recon", 2) is False
    assert policy.scope_allows("admin", 3) is True


# --- rate limiter ----------------------------------------------------------


def test_rate_limiter_overall_cap(monkeypatch):
    monkeypatch.setenv(policy.RATE_LIMIT_ENV, "2")
    monkeypatch.setenv(policy.RATE_LIMIT_TIER3_ENV, "100")
    clock = {"t": 0.0}
    rl = policy.RateLimiter(clock=lambda: clock["t"])

    assert rl.check("tok", 1)[0] is True
    assert rl.check("tok", 1)[0] is True
    assert rl.check("tok", 1)[0] is False  # 3rd in window blocked

    clock["t"] = 61.0  # new window
    assert rl.check("tok", 1)[0] is True


def test_rate_limiter_tier3_is_tighter(monkeypatch):
    monkeypatch.setenv(policy.RATE_LIMIT_ENV, "100")
    monkeypatch.setenv(policy.RATE_LIMIT_TIER3_ENV, "1")
    rl = policy.RateLimiter(clock=lambda: 0.0)

    assert rl.check("tok", 3)[0] is True
    allowed, reason = rl.check("tok", 3)
    assert allowed is False
    assert "Tier 3" in reason
    # A non-tier3 call from the same token is still fine (under overall cap).
    assert rl.check("tok", 1)[0] is True


# --- evaluate_request ------------------------------------------------------


def _rl():
    return policy.RateLimiter(clock=lambda: 0.0)


def test_evaluate_rejects_bad_token():
    d = policy.evaluate_request("Bearer nope", b"", _rl())
    assert d.ok is False and d.status == 401


def test_evaluate_allows_non_tool_call(monkeypatch):
    monkeypatch.setenv(policy.SCOPE_TOKEN_ENVS["recon"], "r1")
    body = json.dumps({"method": "tools/list"}).encode()
    d = policy.evaluate_request("Bearer r1", body, _rl())
    assert d.ok is True and d.scope == "recon"


def test_evaluate_blocks_scope_violation(monkeypatch):
    monkeypatch.setenv(policy.SCOPE_TOKEN_ENVS["recon"], "r1")
    body = json.dumps({"method": "tools/call", "params": {"name": "wp_eval"}}).encode()
    d = policy.evaluate_request("Bearer r1", body, _rl())
    assert d.ok is False and d.status == 403
    assert "wp_eval" in d.message


def test_evaluate_allows_in_scope_call(monkeypatch):
    monkeypatch.setenv(policy.SCOPE_TOKEN_ENVS["admin"], "a1")
    body = json.dumps({"method": "tools/call", "params": {"name": "wp_eval"}}).encode()
    d = policy.evaluate_request("Bearer a1", body, _rl())
    assert d.ok is True


def test_evaluate_rate_limits(monkeypatch):
    monkeypatch.setenv(policy.SCOPE_TOKEN_ENVS["recon"], "r1")
    monkeypatch.setenv(policy.RATE_LIMIT_ENV, "1")
    rl = _rl()
    body = json.dumps({"method": "tools/call", "params": {"name": "wp_recon"}}).encode()
    assert policy.evaluate_request("Bearer r1", body, rl).ok is True
    d = policy.evaluate_request("Bearer r1", body, rl)
    assert d.ok is False and d.status == 429


# --- ASGI middleware -------------------------------------------------------


class _StubApp:
    def __init__(self):
        self.received_body = None

    async def __call__(self, scope, receive, send):
        chunks = []
        while True:
            msg = await receive()
            chunks.append(msg.get("body", b""))
            if not msg.get("more_body", False):
                break
        self.received_body = b"".join(chunks)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _run_request(mw, auth_header, body: bytes):
    scope = {
        "type": "http",
        "headers": [(b"authorization", auth_header.encode())] if auth_header else [],
    }
    sent = []
    chunks = iter([{"type": "http.request", "body": body, "more_body": False}])

    async def receive():
        try:
            return next(chunks)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(mw(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body_out = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body_out


def test_middleware_passes_through_and_replays_body(monkeypatch):
    monkeypatch.setenv(policy.SCOPE_TOKEN_ENVS["admin"], "a1")
    stub = _StubApp()
    mw = PolicyMiddleware(stub)
    body = json.dumps({"method": "tools/call", "params": {"name": "wp_eval"}}).encode()

    status, _ = _run_request(mw, "Bearer a1", body)

    assert status == 200
    assert stub.received_body == body  # downstream saw the original bytes intact


def test_middleware_blocks_scope_violation(monkeypatch):
    monkeypatch.setenv(policy.SCOPE_TOKEN_ENVS["recon"], "r1")
    stub = _StubApp()
    mw = PolicyMiddleware(stub)
    body = json.dumps({"method": "tools/call", "params": {"name": "wp_eval"}}).encode()

    status, out = _run_request(mw, "Bearer r1", body)

    assert status == 403
    assert stub.received_body is None  # never reached downstream
    assert b"wp_eval" in out


def test_middleware_rejects_missing_token():
    stub = _StubApp()
    mw = PolicyMiddleware(stub)
    status, _ = _run_request(mw, None, b"")
    assert status == 401
