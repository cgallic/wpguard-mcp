"""wpguard-mcp server entrypoint.

Builds a FastMCP server, registers every Tier 1/2/3 and packet-lifecycle
tool, wraps the streamable-HTTP ASGI app with a bearer-token auth
middleware, and runs it under uvicorn on 127.0.0.1 by default.

Run it with:

    WPGUARD_MCP_TOKEN=<your-token> python -m wpguard_mcp.server

or, once installed:

    WPGUARD_MCP_TOKEN=<your-token> wpguard-mcp
"""
from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from . import policy
from .tools import mutate, packets, recon

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8642

mcp = FastMCP(
    name="wpguard-mcp",
    instructions=(
        "Safely recon, mutate, and verify WordPress sites through named, guarded verbs "
        "instead of raw PHP/eval. Mutations require an open change packet (packet_open) "
        "before apply=True will run. Typical flow: site_register -> wp_recon -> packet_open "
        "-> mutate tool with apply=False (dry-run, the default) -> review the preview -> "
        "mutate tool again with apply=True -> verify with a Tier 1 read -> packet_close."
    ),
    host=os.environ.get("WPGUARD_MCP_HOST", DEFAULT_HOST),
    port=int(os.environ.get("WPGUARD_MCP_PORT", str(DEFAULT_PORT))),
)

# --- Tier 1: recon / read-only, no packet required ---
mcp.tool()(recon.wp_recon)
mcp.tool()(recon.wp_get_option)
mcp.tool()(recon.wp_get_post_meta)
mcp.tool()(recon.site_list)

# --- Tier 2: guarded named verbs (dry-run by default) ---
mcp.tool()(mutate.wp_mutate_option)
mcp.tool()(mutate.wp_mutate_post_meta)
mcp.tool()(mutate.wp_mutate_post_content)
mcp.tool()(mutate.wp_cache_bust)  # not guarded -- cache only, no content change

# --- Tier 3: guarded raw escape hatch, SSH-only ---
mcp.tool()(mutate.wp_eval)

# --- Packet lifecycle + site registry ---
mcp.tool()(packets.packet_open)
mcp.tool()(packets.packet_approve)
mcp.tool()(packets.packet_log)
mcp.tool()(packets.packet_close)
mcp.tool()(packets.packet_list)
mcp.tool()(packets.site_register)


class PolicyMiddleware:
    """Pure-ASGI middleware enforcing auth, token scope, and rate limits.

    Applied ahead of every route, including MCP protocol endpoints -- there is
    no unauthenticated health-check or discovery route in v1. It buffers the
    request body (so it can see which tool a `tools/call` targets), asks
    `policy.evaluate_request` for a decision, and either short-circuits with a
    401/403/429 or replays the buffered body downstream unchanged.

    Fails closed: a request with no valid token is rejected, and the server
    refuses to build at all if no tokens are configured.
    """

    def __init__(self, app):
        self.app = app
        self.rate_limiter = policy.RateLimiter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Buffer the whole request body so we can inspect the tool call and
        # still replay the bytes to the downstream app.
        messages = []
        while True:
            message = await receive()
            messages.append(message)
            if not message.get("more_body", False):
                break
        body = b"".join(m.get("body", b"") for m in messages)

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth_header = headers.get(b"authorization", b"").decode("latin-1") or None

        decision = policy.evaluate_request(auth_header, body, self.rate_limiter)
        if not decision.ok:
            await self._send_json(send, decision.status, {"error": decision.message})
            return

        replay = iter(messages)

        async def replay_receive():
            try:
                return next(replay)
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _send_json(send, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_app():
    """Build the ASGI app: FastMCP's streamable-HTTP app wrapped in policy auth."""
    # Fail closed at build/import time too, not just per-request, so a
    # misconfigured deployment (no tokens) doesn't silently start listening.
    policy.require_configured()
    app = mcp.streamable_http_app()
    return PolicyMiddleware(app)


def main() -> None:
    """Console-script entrypoint: run the server over streamable-HTTP with uvicorn."""
    import uvicorn

    app = build_app()
    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port, log_level=mcp.settings.log_level.lower())


if __name__ == "__main__":
    main()
