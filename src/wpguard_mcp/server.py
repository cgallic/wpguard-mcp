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

import os

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import auth
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
mcp.tool()(packets.packet_log)
mcp.tool()(packets.packet_close)
mcp.tool()(packets.packet_list)
mcp.tool()(packets.site_register)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Rejects every request that doesn't carry the configured bearer token.

    Applied ahead of every route on the app, including MCP protocol
    endpoints -- there is no unauthenticated health-check or discovery route
    in v1. Fails closed: a misconfigured (missing-token) server returns 500
    on every request rather than accepting unauthenticated traffic.
    """

    async def dispatch(self, request: Request, call_next):
        header = request.headers.get("authorization")
        try:
            authorized = auth.check_bearer_token(header)
        except auth.AuthError as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
        if not authorized:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_app():
    """Build the ASGI app: FastMCP's streamable-HTTP app wrapped in bearer auth."""
    # Fail closed at build/import time too, not just per-request, so a
    # misconfigured deployment doesn't silently start listening at all.
    auth.get_expected_token()
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware)
    return app


def main() -> None:
    """Console-script entrypoint: run the server over streamable-HTTP with uvicorn."""
    import uvicorn

    app = build_app()
    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port, log_level=mcp.settings.log_level.lower())


if __name__ == "__main__":
    main()
