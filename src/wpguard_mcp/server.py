"""wpguard-mcp server entrypoint."""
from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from . import policy
from .tools import (
    blocks,
    cli_jobs,
    eval_sandbox,
    files,
    magic_login,
    mutate,
    packets,
    recon,
    rollback,
    schema_recon,
    skills,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8642

mcp = FastMCP(
    name="wpguard-mcp",
    instructions=(
        "Enterprise-grade WordPress MCP server. Recon, execute sandboxed PHP, manage files, "
        "compose Gutenberg blocks, launch async WP-CLI background jobs, generate magic login links, "
        "manage skills playbooks, and safely mutate WordPress sites with automatic snapshots, dry-run "
        "previews, and 1-click rollback."
    ),
    host=os.environ.get("WPGUARD_MCP_HOST", DEFAULT_HOST),
    port=int(os.environ.get("WPGUARD_MCP_PORT", str(DEFAULT_PORT))),
)

# --- Tier 1: Recon & Discovery ---
mcp.tool()(recon.wp_recon)
mcp.tool()(recon.wp_get_option)
mcp.tool()(recon.wp_get_post_meta)
mcp.tool()(recon.site_list)
mcp.tool()(schema_recon.wp_schema_recon)
mcp.tool()(schema_recon.wp_db_query)

# --- Tier 2: Guarded Named Verbs & Content ---
mcp.tool()(mutate.wp_mutate_option)
mcp.tool()(mutate.wp_mutate_post_meta)
mcp.tool()(mutate.wp_mutate_post_content)
mcp.tool()(mutate.wp_cache_bust)

# --- Runtime & Execution Sandbox ---
mcp.tool()(eval_sandbox.wp_eval_sandbox)
mcp.tool()(eval_sandbox.wp_snippet_save)
mcp.tool()(eval_sandbox.wp_snippet_toggle)
mcp.tool()(eval_sandbox.wp_snippet_list)
mcp.tool()(mutate.wp_eval)

# --- Guarded Filesystem Operations ---
mcp.tool()(files.wp_file_read)
mcp.tool()(files.wp_file_write)
mcp.tool()(files.wp_file_edit)
mcp.tool()(files.wp_file_tree)
mcp.tool()(files.wp_file_delete)

# --- Async WP-CLI Task Runner ---
mcp.tool()(cli_jobs.wp_cli_run)
mcp.tool()(cli_jobs.wp_cli_job_start)
mcp.tool()(cli_jobs.wp_cli_job_status)
mcp.tool()(cli_jobs.wp_cli_job_cancel)

# --- Gutenberg Block Suite ---
mcp.tool()(blocks.wp_block_parse)
mcp.tool()(blocks.wp_block_compose)
mcp.tool()(blocks.wp_block_validate)
mcp.tool()(blocks.wp_post_create)

# --- Magic Login & Browser Automation ---
mcp.tool()(magic_login.wp_magic_login)

# --- In-WordPress Skills & Design Context ---
mcp.tool()(skills.wp_skill_save)
mcp.tool()(skills.wp_skill_get)
mcp.tool()(skills.wp_skill_list)
mcp.tool()(skills.wp_design_context)

# --- Rollback Engine ---
mcp.tool()(rollback.wp_rollback)

# --- Packet lifecycle + site registry ---
mcp.tool()(packets.packet_open)
mcp.tool()(packets.packet_approve)
mcp.tool()(packets.packet_log)
mcp.tool()(packets.packet_close)
mcp.tool()(packets.packet_list)
mcp.tool()(packets.site_register)


class PolicyMiddleware:
    def __init__(self, app):
        self.app = app
        self.rate_limiter = policy.RateLimiter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

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
    policy.require_configured()
    app = mcp.streamable_http_app()
    return PolicyMiddleware(app)


def main() -> None:
    import uvicorn
    app = build_app()
    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port, log_level=mcp.settings.log_level.lower())


if __name__ == "__main__":
    main()
