# Per-client setup

wpguard-mcp is a **streamable-HTTP** MCP server that requires a bearer token on
every request. Any client that can point at an HTTP MCP URL and send an
`Authorization` header works. Below are copy-pasteable snippets for the common
clients.

Start the server first:

```bash
export WPGUARD_TOKEN_ADMIN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
wpguard-mcp
# -> http://127.0.0.1:8642/mcp
```

The examples use the admin-scoped token because they cover the full preview,
packet, and apply workflow. Use `WPGUARD_TOKEN_RECON` for read-only clients or
`WPGUARD_TOKEN_MUTATE` when raw administrative tools are unnecessary. See
[token configuration](getting-started.md#connect-your-mcp-client). The endpoint
is `http://127.0.0.1:8642/mcp` unless you overrode host or port.

> These snippets follow each client's documented HTTP-MCP-with-custom-header
> format. The server's transport (streamable HTTP + `Authorization: Bearer`)
> was validated end-to-end: an `initialize` handshake succeeds with a valid
> token and is rejected (401) without one.

## Claude Code

Add it with the CLI:

```bash
claude mcp add --transport http wpguard http://127.0.0.1:8642/mcp \
  --header "Authorization: Bearer ${WPGUARD_TOKEN_ADMIN}"
```

Or in `.mcp.json` (project-scoped) / your user config:

```json
{
  "mcpServers": {
    "wpguard": {
      "type": "http",
      "url": "http://127.0.0.1:8642/mcp",
      "headers": { "Authorization": "Bearer ${WPGUARD_TOKEN_ADMIN}" }
    }
  }
}
```

## Cursor

`~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (project):

```json
{
  "mcpServers": {
    "wpguard": {
      "url": "http://127.0.0.1:8642/mcp",
      "headers": { "Authorization": "Bearer ${env:WPGUARD_TOKEN_ADMIN}" }
    }
  }
}
```

## Windsurf

`~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "wpguard": {
      "serverUrl": "http://127.0.0.1:8642/mcp",
      "headers": { "Authorization": "Bearer <TOKEN>" }
    }
  }
}
```

## Codex

Add a native Streamable HTTP connection in `~/.codex/config.toml`:

```toml
[mcp_servers.wpguard]
url = "http://127.0.0.1:8642/mcp"
bearer_token_env_var = "WPGUARD_TOKEN_ADMIN"
```

Make the same server token available in the environment of the Codex process.
See [OpenAI's MCP configuration documentation](https://developers.openai.com/codex/mcp).

## Verifying the connection

Once connected, the safest first call is a read-only Tier 1 tool:

```
site_list          # lists registered sites (empty until you site_register)
```

Then register a site and recon it before doing anything that writes. See the
[first-edit guide](getting-started.md#preview-your-first-edit) for the full propose → approve → apply
flow.

## Troubleshooting

- **401 Unauthorized** — the `Authorization` header is missing or the token
  doesn't match. Confirm the client actually sends the header and that it
  matches the configured scoped token. For Codex, the environment variable
  contains the raw token without the `Bearer ` prefix.
- **403 Forbidden on a write tool** — your token's scope is too low for that
  tool's tier (e.g. a `recon` token calling `wp_mutate_option`). Use a
  higher-scoped token.
- **429 Too Many Requests** — you hit the per-token rate limit; back off. Tier 3
  (`wp_eval`) has a tighter limit than Tier 1/2.
- **Connection refused** — the server binds to `127.0.0.1` by default; the
  client must run on the same host (or reach it over a tunnel you set up).
