# Get started with WPGuard

Run the server, connect an MCP client, and register a WordPress site. Choose a staging site for your first edit so you can inspect the result before using the same workflow in production.

## Install from this repository

You need Git and Python 3.10 or newer. For the SSH connection, the server machine also needs an SSH client and the remote host needs WP-CLI. For the companion connection, you need permission to install and activate a WordPress plugin.

### macOS or Linux

```bash
git clone https://github.com/cgallic/wpguard-mcp.git
cd wpguard-mcp
python -m venv .venv
source .venv/bin/activate
python -m pip install ".[browser]"
playwright install chromium
export WPGUARD_TOKEN_ADMIN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
wpguard-mcp
```

### Windows PowerShell

```powershell
git clone https://github.com/cgallic/wpguard-mcp.git
Set-Location wpguard-mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[browser]"
& .\.venv\Scripts\playwright.exe install chromium
$env:WPGUARD_TOKEN_ADMIN = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
& .\.venv\Scripts\wpguard-mcp.exe
```

The generated token exists in that shell's environment. Store it in your secret manager or service configuration for subsequent starts. Configure the same value in the MCP client's authorization header. The Python entry point does not automatically load a `.env` file.

### Build with Docker Compose

From the cloned repository:

```bash
cp .env.example .env
```

Set a long random `WPGUARD_TOKEN_ADMIN` value in `.env`, then run:

```bash
docker compose up -d --build
```

Compose builds this checkout. It binds the published port to `127.0.0.1:8642`, runs the server on `0.0.0.0:8642` inside the container, and persists `/state` in a named volume. The explicit container settings override the native defaults in `.env.example`.

SSH connections from a container also need correctly mounted SSH credentials and known-host configuration; a native installation can use the server user's existing SSH setup.

## Connect your MCP client

Configure an MCP **Streamable HTTP** connection with:

| Field | Value |
|---|---|
| URL | `http://127.0.0.1:8642/mcp` |
| Header name | `Authorization` |
| Header value | `Bearer <your server token>` |

Client configuration formats differ; these are connection values, not a universal JSON configuration. A remotely hosted client cannot reach your computer through its own `127.0.0.1`. For remote access, deploy the server behind an authenticated HTTPS endpoint appropriate to your environment.

The server requires at least one configured token. Available scopes are:

| Environment variable | Access |
|---|---|
| `WPGUARD_TOKEN_RECON` | Discovery and read tools. Some tools, such as magic login, have additional side effects; inspect the tool definition. |
| `WPGUARD_TOKEN_MUTATE` | Recon tools, named mutation tools, site registration, and packet approval. |
| `WPGUARD_TOKEN_ADMIN` | All tools, including correction registration/retirement and advanced CLI/raw PHP tools. |

`WPGUARD_MCP_TOKEN` remains an admin-scoped alias. Each scoped variable accepts comma-separated tokens. Scopes are instance-wide, not per-client tenant boundaries.

## Register a site

The examples below are MCP tool calls. They are not standalone Python scripts. Use an admin or mutate token to call `site_register`.

### SSH and WP-CLI

```python
site_register(
    name="restaurant-staging",
    transport="ssh",
    ssh_host="staging.example.com",
    ssh_user="wordpress",
    wp_path="/var/www/wordpress",
)
```

Use a host and path that your server's SSH identity can actually access. For a Bedrock installation, set `layout="bedrock"` and `wp_path` to the project root; WPGuard resolves WordPress under `web/wp`.

### Companion plugin

Copy `wp-plugin/wpguard-companion.php` from this checkout into a `wpguard-companion` directory under your site's `wp-content/plugins/`, then activate **WPGuard Companion** in WordPress.

Generate a separate random key and set it in `wp-config.php`:

```php
define('WPGUARD_COMPANION_API_KEY', 'your-separate-long-random-key');
```

Set the same value as `WPGUARD_RESTAURANT_KEY` in the server process's environment. If using Docker, add it to the `.env` file before starting the container. Register the name of the environment variable, never its secret value:

```python
site_register(
    name="restaurant-staging",
    transport="companion_plugin",
    plugin_url="https://staging.example.com/wp-json/wpguard/v1/exec",
    plugin_api_key_env="WPGUARD_RESTAURANT_KEY",
)
```

The plugin key authorizes its administrative command set, including PHP and file operations. Keep the key server-side. The MCP server's token scopes and packet checks do not protect direct requests made with that plugin key.

## Preview your first edit

Call `wp_site_context(site="restaurant-staging")` to confirm the site and review the available context. Then ask for a preview using `wp_mutate_option`, `wp_mutate_post_meta`, or `wp_mutate_post_content` with `apply=False`.

For example:

```python
wp_mutate_option(
    site="restaurant-staging",
    option_name="blogdescription",
    new_value="Seasonal food, freshly prepared.",
    apply=False,
)
```

Review the old and proposed values, `corrections` result, `etag`, and `change_digest`. An uncovered target reports `not_covered`; that is not a passing correction check.

To apply this reviewed change:

1. Call `packet_open` with the site, a specific summary, `target="option:blogdescription"`, `verb="wp_mutate_option"`, and the exact `change_digest` from the preview.
2. Call `packet_approve` with the returned `packet_id` and your approver identifier.
3. Repeat the mutation with the same values, `apply=True`, and `expected_etag` from the preview.
4. Re-read the option and inspect the relevant page. Log the observed outcome and close the packet using `packet_log` and `packet_close`.

A mutate-scoped caller can perform both proposal and approval. If your workflow requires a separate human reviewer, enforce that separation outside these tool calls.

For the three correction-aware tools, failing or unevaluable applicable corrections block apply. Successful writes capture a snapshot and record their packet association. Read the returned results rather than assuming an approval or request guarantees a completed write.

## Finish one page from an approved reference

For Gutenberg and classic page bodies, use `wp_page_list` to find the target and approved reference page. Call `wp_page_compare` with both IDs and any exact strings that must survive. The comparison is read-only and returns page hashes, a bounded diff, correction results, and a protected-copy report.

Prepare the complete proposed target content, then call `wp_page_replace_content(..., apply=False)`. Review its diff, protected-copy report, `etag`, and `change_digest`. Open and approve an exact packet with `target="post:<page_id>:content"`, `verb="wp_page_replace_content"`, and that digest. Apply with the same arguments and the preview's `expected_etag`.

WPGuard refuses the write if the page changed after preview, if a configured correction fails, or if named protected copy was removed. A successful write captures a snapshot and reads the stored content back. Then call `wp_page_render_verify` with the same site and page ID. Pass a distinctive approved string as `expected_text` when useful. Review the desktop and mobile screenshots, hashes, and checks in its evidence receipt before closing the packet.

Rendered verification checks the live page for HTTP failures, horizontal overflow, broken rendered images, and expected text. It does not judge visual quality or exercise interactions and links, so the screenshot review remains part of approval.

## Review records and keep state private

```bash
wpguard audit --site restaurant-staging
wpguard audit --since 7d --json
```

`WPGUARD_STATE_DIR` defaults to `state` relative to the working directory. It holds site connection details, packet and snapshot ledgers, imported histories, and correction records. Use the same directory for subsequent server and audit runs. Keep a backup and restrict access to it.

The default state directory is Git-ignored. A custom state directory still needs your own repository exclusions and filesystem access controls. Imported histories are not public product examples: MCP queries can share selected records with the connected client, so choose the client and its data handling accordingly.

Optional webhook/cloud integrations are configured separately. Leave their environment settings unset unless you intend to share event data. `WPGUARD_BYPASS_GUARD=1` bypasses packet approval and is intended for development; it does not disable applicable correction checks.

See the [README](../README.md#know-the-boundaries) for current coverage and [SECURITY.md](../SECURITY.md) for the trust model.
