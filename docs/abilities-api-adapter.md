# Abilities API / MCP Adapter as a third wpguard transport

**Status: proposal / design sketch only. Nothing described in this document is
implemented.** There is no `transports/abilities_api.py` in this repo,
`SiteConfig.transport` does not accept an `"abilities_api"` value,
`policy.TOOL_TIERS` and `GUARDED_TOOLS` are unchanged, and no tool in
`tools/recon.py` / `tools/mutate.py` / `tools/packets.py` has a third
transport branch. This document records research findings on WordPress's own
Abilities API and MCP Adapter, then sketches how wpguard *could* add them as a
third transport option alongside `ssh_wpcli` and `companion_plugin` — so the
idea can be reviewed and scoped before any code is written. Treat every code
block below as illustrative, not as a diff to apply.

## 1. TL;DR

- WordPress core (6.9, merged November 2025) now ships a built-in **Abilities
  API**: a registry (`wp_register_ability()`) for named, schema-typed,
  permission-checked, remotely-invocable units of functionality, with its own
  REST surface at `/wp-abilities/v1/...`.
- A separate, actively-evolving **MCP Adapter** package (announced February
  2026, `github.com/WordPress/mcp-adapter`, pre-1.0) translates registered
  abilities into MCP tools/resources/prompts and serves them over STDIO
  (via WP-CLI) or HTTP.
- For wpguard's purposes — a single trusted process calling a small, fixed
  set of named verbs on a remote site — the more useful integration point is
  **the Abilities API's own REST surface directly**, not the MCP Adapter's
  MCP-speaking endpoint. wpguard doesn't need to *be* a generic MCP client to
  another MCP server; it just needs an authenticated, discoverable, callable
  REST verb, which the Abilities API already provides on any WP 6.9+ site
  with zero additional plugin installed.
- The catch: **WordPress core today only ships read-only abilities**
  (`core/get-site-info`, `core/get-user-info`, `core/get-environment-info`).
  Nothing in core registers an ability shaped like wpguard's
  `wp_mutate_option` or `wp_mutate_post_content`. Until third-party plugins
  widely adopt the Abilities API for mutations, realistic Tier-2 coverage
  still depends on *something* on the target site registering the right
  abilities — most likely a small wpguard-authored companion (see §5.5),
  which is a smaller, more standards-aligned artifact than today's
  `wp-plugin/wpguard-companion.php`, but is not "zero-install" for mutations
  in the near term.
- The proposal preserves wpguard's guard/packet/snapshot/policy layer
  unchanged. The new transport only changes *how* an already-authorized
  write reaches the site, exactly like `companion_plugin` does today next to
  `ssh_wpcli`.

## 2. wpguard today, for grounding

(See `src/wpguard_mcp/transports/ssh_wpcli.py`,
`src/wpguard_mcp/transports/companion_plugin.py`,
`src/wpguard_mcp/tools/recon.py`, `src/wpguard_mcp/tools/mutate.py`,
`src/wpguard_mcp/tools/packets.py`, `src/wpguard_mcp/guard.py`,
`src/wpguard_mcp/config.py`, `src/wpguard_mcp/policy.py` for the full
picture; this section is a two-minute recap.)

- **Two transports today**, selected per-site by `SiteConfig.transport`
  (`config.py`, `VALID_TRANSPORTS = ("ssh", "companion_plugin")`):
  - `ssh_wpcli.py` shells out to the system `ssh` binary and runs `wp-cli`
    remotely. It is the *only* transport allowed to reach Tier 3 (`wp_eval`).
  - `companion_plugin.py` POSTs a whitelisted `command` + JSON `args` to one
    REST route (`/wp-json/wpguard/v1/exec`) exposed by
    `wp-plugin/wpguard-companion.php`, authenticated with a shared-secret
    `X-WPGuard-Key` header. Its `ALLOWED_COMMANDS` set deliberately excludes
    anything eval-shaped.
- **Three tool tiers** (`policy.py`, `TOOL_TIERS`, fail-closed default of
  tier 3 for anything unmapped):
  - Tier 1 recon (`tools/recon.py`): `wp_recon`, `wp_get_option`,
    `wp_get_post_meta`, `site_list`. No change packet required. Output is
    wrapped as untrusted content and scanned for injection-like phrasing
    (`recon_safety.py`).
  - Tier 2 guarded named verbs (`tools/mutate.py`): `wp_mutate_option`,
    `wp_mutate_post_meta`, `wp_mutate_post_content` (all dry-run-by-default,
    etag-guarded, packet-gated), plus unguarded `wp_cache_bust`.
  - Tier 3 raw escape hatch: `wp_eval`, hardcoded SSH-only — `mutate.py`
    raises `ValueError` if called against a `companion_plugin`-transport
    site.
- **One shared guard gate** (`guard.py`, `require_approved_packet`): every
  Tier 2/3 `apply=True` call funnels through this single function. It
  requires an *approved*, still-open, target-matching, change-digest-matching
  packet (`packets.py`: `packet_open` → `packet_approve` → the mutate call →
  `packet_close`), or the explicit `WPGUARD_BYPASS_GUARD=1` dev escape valve.
  `SnapshotStore` records the previous value before every write, enabling
  optional durable re-verification on `packet_close`.
- **Policy is transport-agnostic already**: `policy.TOOL_TIERS` maps tool
  *names* to tiers, not transports. Token scope (`recon`/`mutate`/`admin`)
  and rate limiting are enforced by `PolicyMiddleware` in `server.py` before
  any tool function runs, regardless of which transport that site uses. This
  matters below: adding a transport should require zero changes to
  `policy.py`.

## 3. What WordPress shipped

### 3.1 The Abilities API (WordPress core, 6.9+)

Merged into WordPress core with the 6.9 release (make.wordpress.org dev note,
November 2025)[^1]. On WP 6.8 and earlier it must be installed separately as
a Composer package or feature plugin; on 6.9+ it needs nothing extra.

Registration is a single function call, conventionally on the
`wp_abilities_api_init` hook (categories must be registered first, on
`wp_abilities_api_categories_init`)[^2][^3]:

```php
wp_register_ability( string $name, array $args ): ?WP_Ability
```

- `$name` — namespaced identifier, `namespace/ability-name`, lowercase
  alphanumerics/dashes/one slash.
- `$args`:
  | key | type | required | purpose |
  |---|---|---|---|
  | `label` | string | yes | human-readable name |
  | `description` | string | yes | what it does |
  | `category` | string | yes | must be pre-registered via `wp_register_ability_category()` |
  | `execute_callback` | callable | yes | does the actual work; receives validated input, returns a result or `WP_Error` |
  | `permission_callback` | callable | yes | receives the *same input* as the execute callback; returns `bool` or `WP_Error` |
  | `input_schema` | array (JSON Schema) | no, but recommended | validates/documents accepted input |
  | `output_schema` | array (JSON Schema) | no | validates/documents the return shape |
  | `meta` | array | no | includes `annotations` and `show_in_rest` (per-ability REST visibility) and, when the MCP Adapter is active, `mcp.public` (see §3.2) |
  | `ability_class` | string | no | custom subclass of `WP_Ability` |

Example from the official function reference[^2]:

```php
wp_register_ability(
    'my-plugin/analyze-text',
    array(
        'label'               => __( 'Analyze Text', 'my-plugin' ),
        'description'         => __( 'Performs sentiment analysis on text.', 'my-plugin' ),
        'category'            => 'text-processing',
        'input_schema'        => array( 'type' => 'string', 'minLength' => 10 ),
        'execute_callback'    => 'my_plugin_analyze_text',
        'permission_callback' => 'my_plugin_can_analyze_text',
    )
);
```

The invocation order is fixed and enforced by the API itself, not by the
caller: **validate input against `input_schema` → run `permission_callback`
→ run `execute_callback` → validate output against `output_schema`**[^3].
This is architecturally close to what wpguard's own `mutate.py` already does
by hand (compute etag/digest → gate on packet → snapshot → write) — the
Abilities API gives WordPress-side plugin authors a standard shape for the
"gate before executing" pattern that wpguard has been hand-rolling per tool.

Retrieval/introspection helpers: `wp_get_ability( $name )`,
`wp_get_abilities()`, `wp_has_ability( $name )`; the `WP_Ability` object
exposes `execute()`, `check_permissions()`, `get_input_schema()`,
`get_output_schema()`, `get_meta()`, etc.[^3]

**REST surface** (auth required on every route; execution is additionally
gated by the ability's own `permission_callback`)[^4]:

| method | path | purpose |
|---|---|---|
| GET | `/wp-abilities/v1/abilities` | list registered abilities (paginated, filterable by `category`) |
| GET | `/wp-abilities/v1/categories` | list categories |
| GET | `/wp-abilities/v1/categories/{slug}` | one category |
| GET | `/wp-abilities/v1/{namespace}/{ability}` | metadata + schema for one ability |
| GET / POST / DELETE | `/wp-abilities/v1/{namespace}/{ability}/run` | **execute** the ability; input via query string (GET/DELETE) or JSON body (POST) |

This REST surface exists independently of the MCP Adapter — it is plain
WordPress core REST API, authenticated the normal WordPress way (Application
Passwords over HTTPS being the standard, plugin-free option since WP 5.6, or
cookie/nonce auth for logged-in browser contexts, or a custom auth plugin).

Default abilities shipped by core itself are read-only recon-shaped:
`core/get-site-info`, `core/get-user-info`, `core/get-environment-info`[^5].
Core does not ship any mutating ability as of this research.

The standalone `WordPress/abilities-api` feature-plugin repo that incubated
this work was archived (read-only) on **February 5, 2026** once the core
proposal landed[^6] — a signal the project considers the core merge the
canonical home now, not the standalone plugin.

Forward-looking note: a **client-side (JavaScript) Abilities API** was
proposed for WordPress 7.0 (~March 2026)[^7] — extending the same
registration/discovery idea into the block editor's JS runtime. This is
almost certainly irrelevant to wpguard's server-side automation use case,
but it's evidence the API surface is still actively growing, which bears on
the version-skew risk in §7.

### 3.2 The MCP Adapter

A separate Composer package, `wordpress/mcp-adapter`
(`github.com/WordPress/mcp-adapter`, Packagist), announced via the WordPress
Developer Blog in February 2026[^8][^9]. It is **not** currently listed on
the wordpress.org plugin directory — it's obtained via Composer (recommended)
or a GitHub release[^10]. It supersedes an earlier Automattic-maintained
prototype (`Automattic/wordpress-mcp`), whose repo now says explicitly it
"will be deprecated as stable releases of mcp-adapter become available"[^11].

Its job: adapt registered Abilities into MCP primitives (tools, resources,
prompts) and serve them over one or more transports. Core pieces per the
repo's own docs[^9]:

- **Ability Registry** — abilities registered via `wp_register_ability()`.
- **Server Manager** — creates one or more independently-configured MCP
  servers (`$adapter->create_server(...)`).
- **Transport Layer** — STDIO and HTTP built in; a `McpTransportInterface`
  for custom transports.
- **Error & Observability handlers** — pluggable logging/metrics.

Two ways abilities become reachable:

1. **Default server** (`mcp-adapter-default-server`, REST-exposed at
   `/wp-json/mcp/mcp-adapter-default-server`): individual abilities are
   *not* listed directly in `tools/list`. Instead the adapter exposes three
   fixed meta-tools that discover/describe/invoke abilities indirectly
   (naming varies slightly across the adapter's own docs/blog post —
   confirm exact tool names against the running server before implementing
   against them):
   - discover-abilities — enumerate what's available
   - get-ability-info — fetch one ability's schema/description
   - execute-ability — actually invoke `{ability_name, input}`

   Only abilities explicitly opted in via `'meta' => ['mcp' => ['public' =>
   true]]` at registration time are reachable this way[^8].

2. **Custom servers**, created explicitly by a plugin:

   ```php
   add_action( 'mcp_adapter_init', function ( $adapter ) {
       $adapter->create_server(
           'my-server-id',
           'my-namespace',
           'mcp',
           'My MCP Server',
           'Description of my server',
           'v1.0.0',
           array( \WP\MCP\Transport\HttpTransport::class ),
           \WP\MCP\Infrastructure\ErrorHandling\ErrorLogMcpErrorHandler::class,
           \WP\MCP\Infrastructure\Observability\NullMcpObservabilityHandler::class,
           array( 'my-plugin/my-ability' ),   // abilities exposed as direct MCP tools
       );
   } );
   ```

   Here the listed abilities show up as normal, individually-named MCP
   tools in `tools/list` — no meta-tool indirection, and no `meta.mcp.public`
   flag needed, since the server itself is the allowlist[^8][^9].

**Transports**[^8][^9][^12]:

- **STDIO** — local/dev only, runs through WP-CLI as a subprocess:
  `wp --path=/path/to/wordpress mcp-adapter serve --server=<id>
  --user={admin_user}`.
- **HTTP** — a REST-backed transport described as implementing a
  Streamable-HTTP-style MCP transport (`/wp-json/<namespace>/<route>`); for
  *remote* access from an otherwise-STDIO-only desktop client (e.g. Claude
  Desktop), WordPress publishes a companion Node.js bridge,
  `@automattic/mcp-wordpress-remote`, which proxies STDIO ↔ the site's HTTP
  endpoint and authenticates with WordPress Application Passwords
  (`WP_API_USERNAME` / `WP_API_PASSWORD`) or a custom OAuth setup. A process
  that can already speak HTTP on its own — which wpguard can — has no need
  for that Node proxy; it would call the HTTP transport directly.
- **Custom transports** via `McpTransportInterface`.
- Multiple transports can be attached to the same server simultaneously.

**Permission model — two layers, not one**[^13]:

1. **Transport-level `permission_callback`**, passed when the server is
   created. Default is `is_user_logged_in()`. For `HttpTransport` it
   receives the raw `\WP_REST_Request`, so it can inspect headers (e.g.
   check a custom API-key header instead of relying on cookie/application-
   password auth alone). Docs frame this explicitly as "act[ing] as a
   gatekeeper — if blocked here, users cannot access ANY abilities on that
   server" and recommend setting it to the *broadest* capability any ability
   on the server needs, not the narrowest.
2. **Per-ability `permission_callback`**, from the Abilities API
   registration itself (`current_user_can('manage_options')`, etc.) — the
   fine-grained check, run after the transport gate passes and before
   `execute_callback` runs.

Documented guidance explicitly warns against `__return_true` for destructive
abilities and recommends a dedicated, limited-capability WordPress user for
MCP/agent access in production rather than a full administrator[^13] — the
same "least privilege, dedicated credential" advice this repo's README
already gives for the companion-plugin API key.

### 3.3 Timeline and stability

| date | event |
|---|---|
| Nov 2025 | Abilities API merged into WordPress core (6.9) |
| Feb 5, 2026 | standalone `WordPress/abilities-api` feature-plugin repo archived |
| Feb 2026 | MCP Adapter announced on the WordPress Developer Blog |
| ~Mar 2026 | client-side (JS) Abilities API proposed for WP 7.0 |
| ~Apr 15, 2026 | mcp-adapter v0.5.0 (latest seen during this research), with documented breaking changes vs. v0.3.0 (transport, observability, and hook-name changes) |

Read together: **the Abilities API itself is core, but young (~8 months old
at the time of writing this doc)**; **the MCP Adapter is a separate,
pre-1.0, Composer-distributed package with an already-nonzero history of
breaking changes between minor versions**. See §7.1.

## 4. Why this is attractive for wpguard

- **Lower install bar than the companion plugin, for read-only recon at
  least.** Any WP 6.9+ site already has an authenticated, discoverable,
  schema-typed REST surface (`/wp-abilities/v1/...`) with zero plugin
  install — today limited to `core/get-site-info` /
  `core/get-user-info` / `core/get-environment-info`, but that surface only
  grows as more plugins adopt `wp_register_ability()`.
- **Standards-based instead of bespoke.** `wp-plugin/wpguard-companion.php`
  is a wpguard-specific REST route with a wpguard-specific header scheme
  (`X-WPGuard-Key`) that only wpguard's own Python client understands. An
  ability-registering companion, by contrast, speaks a protocol WordPress
  core itself defines — any other MCP-aware tool the site owner runs
  (WordPress's own default MCP server, another agent, a future core
  feature) can discover and use the *same* registered abilities. wpguard
  stops being the only consumer that benefits from the site being
  instrumented.
- **Decouples "does this site expose the verb I need" from "did wpguard
  have to write the plugin that provides it."** Once the discovery/mapping
  logic in §5 exists, wpguard doesn't care *who* registered
  `wpguard/mutate-option` — its own companion package, or (eventually) a
  mainstream plugin, or WordPress core itself if it ever ships mutating
  abilities. That is a meaningfully different trajectory than the
  companion-plugin transport, which will never be satisfied by anything
  wpguard didn't write.
- **Sites that already run the adapter for other reasons need nothing
  wpguard-specific installed for the recon-shaped parts of the surface.**
  If a site owner has already wired up the MCP Adapter (e.g. to let Claude
  Desktop or Cursor talk to their site), wpguard registering itself as a
  second consumer of the same underlying Abilities REST API is close to
  free on that site.

The honest caveat, stated plainly so it isn't lost: **this is not, today, a
"no plugin needed" story for Tier 2.** Nothing ships in WordPress core that
maps to `wp_mutate_option` / `wp_mutate_post_meta` /
`wp_mutate_post_content`. Realistically, near-term adoption still requires
*something* — most plausibly a small wpguard-authored ability-registering
package (§5.5) — on the target site. The win is that this "something" is
smaller, more auditable, and more interoperable than the current companion
plugin, not that it disappears entirely.

## 5. Proposed architecture

### 5.1 New transport module: `transports/abilities_api.py`

Mirrors the shape of `transports/companion_plugin.py` closely — same
"resolve config → build request → raise a typed error on failure → return
the unwrapped result" pattern — swapping the custom `/wpguard/v1/exec`
envelope for the Abilities API's own REST shape:

```python
"""HTTPS transport to a WordPress site's built-in Abilities API (WP 6.9+),
optionally fronted by the WordPress MCP Adapter.

Unlike companion_plugin.py, this transport does not require a wpguard-
specific plugin on the target site -- it calls WordPress's own
/wp-abilities/v1/... REST routes. It DOES require that the abilities
wpguard's verbs map to are actually registered on that site (see
ABILITY_MAP / discover()); if one isn't, callers should fall back to
another transport rather than error out blindly (see tools/*.py).

Like companion_plugin, this transport never carries wp_eval / Tier 3 --
that stays SSH-only regardless of what abilities a site happens to expose.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from ..config import SiteConfig

# wpguard verb -> the ability name wpguard expects a site to register for
# it. A site satisfies a verb over this transport only if wp_has_ability()
# (checked remotely via discovery, see discover()) returns true for the
# mapped name. Distinct from policy.TOOL_TIERS, which is about wpguard's
# own auth scopes, not what the remote site has registered.
ABILITY_MAP = {
    "wp_recon": "wpguard/recon",
    "wp_get_option": "wpguard/get-option",
    "wp_get_post_meta": "wpguard/get-post-meta",
    "wp_mutate_option": "wpguard/mutate-option",
    "wp_mutate_post_meta": "wpguard/mutate-post-meta",
    "wp_mutate_post_content": "wpguard/mutate-post-content",
    "wp_cache_bust": "wpguard/cache-bust",
    # wp_eval deliberately has no entry: Tier 3 stays SSH-only regardless
    # of whether a site happens to expose some eval-shaped ability.
}


class AbilitiesApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AbilityNotRegisteredError(AbilitiesApiError):
    """Raised when a verb's mapped ability isn't registered on this site.
    Callers (tools/*.py) should catch this and either surface a clear
    "use a different transport for this site" error, or -- if the site
    config declares a fallback transport -- retry there.
    """


def _auth(site: SiteConfig) -> tuple[str, str]:
    # WordPress Application Passwords: HTTP Basic auth, core-native since
    # WP 5.6, no companion plugin required. The password itself is never
    # read from the registry -- only the env var name holding it is.
    if not (site.abilities_api_username and site.abilities_api_app_password_env):
        raise ValueError(
            f"site '{site.name}' has no abilities_api_username / "
            f"abilities_api_app_password_env configured"
        )
    password = os.environ.get(site.abilities_api_app_password_env, "")
    if not password:
        raise ValueError(
            f"env var '{site.abilities_api_app_password_env}' is not set; cannot "
            f"authenticate to the Abilities API on '{site.name}'"
        )
    return site.abilities_api_username, password


def discover(site: SiteConfig, timeout: float = 10.0) -> set[str]:
    """Return the set of ability names actually registered on `site`, by
    calling GET /wp-abilities/v1/abilities. Requires auth like every other
    Abilities API route -- there is no anonymous capability probe.
    Callers should cache this (with a short TTL / invalidate-on-failure,
    not forever: plugins get activated/deactivated) rather than call it
    per-tool-invocation.
    """
    ...


def call(site: SiteConfig, verb: str, args: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
    """Run the ability mapped from `verb` via POST .../{namespace}/{ability}/run.

    Raises AbilityNotRegisteredError if verb isn't in ABILITY_MAP, or if
    ABILITY_MAP[verb] isn't present in this site's discovered ability set.
    """
    ability = ABILITY_MAP.get(verb)
    if ability is None:
        raise AbilitiesApiError(f"'{verb}' has no Abilities API mapping (by design, e.g. wp_eval)")
    namespace, _, name = ability.partition("/")
    base = site.abilities_api_url.rstrip("/")
    url = f"{base}/wp-json/wp-abilities/v1/{namespace}/{name}/run"

    response = httpx.post(url, json=args or {}, auth=_auth(site), timeout=timeout)
    if response.status_code == 404:
        raise AbilityNotRegisteredError(f"'{ability}' is not registered on '{site.name}'", 404)
    if response.status_code in (401, 403):
        raise AbilitiesApiError(f"permission denied calling '{ability}' on '{site.name}'", response.status_code)
    if response.status_code >= 400:
        raise AbilitiesApiError(f"'{ability}' call failed ({response.status_code}): {response.text}", response.status_code)
    return response.json()
```

This is a sketch to show shape and error taxonomy, not a literal diff —
exact schema shapes, pagination handling in `discover()`, and the
`/run` request shape (query string vs. JSON body, per the real REST docs)
need to be verified against a live WP 6.9+ site during implementation.

### 5.2 Config changes

`config.py`:

- `VALID_TRANSPORTS = ("ssh", "companion_plugin", "abilities_api")`
- New optional `SiteConfig` fields, following the existing per-transport
  field convention (`plugin_url` / `plugin_api_key_env` for
  `companion_plugin`):
  - `abilities_api_url: str | None` — the site's REST base
    (`https://example.com`; the transport appends `/wp-json/wp-abilities/v1/...`)
  - `abilities_api_username: str | None` — the WordPress user the
    Application Password belongs to
  - `abilities_api_app_password_env: str | None` — name of the env var
    holding the Application Password (never the secret itself, matching
    `plugin_api_key_env`'s existing convention)
  - `abilities_fallback_transport: str | None` — optional; one of
    `"ssh"` / `"companion_plugin"`. When set, a verb whose mapped ability
    isn't registered on this site (an `AbilityNotRegisteredError`) is
    retried against this fallback instead of failing outright. The
    fallback reuses whichever `ssh_*` / `plugin_*` fields are already on
    the same `SiteConfig` — no new nested schema, since those fields
    already exist on the dataclass today.
  - `__post_init__` gains a branch requiring `abilities_api_url` and
    `abilities_api_username` and `abilities_api_app_password_env`
    together, same pattern as the existing `companion_plugin` validation.
- `policy.py` needs **no changes** — `TOOL_TIERS` is keyed by tool name,
  not transport, and stays exactly as-is.

### 5.3 Verb → ability mapping

| wpguard tool | tier | mapped ability | registered by WP core today? |
|---|---|---|---|
| `wp_recon` | 1 | `wpguard/recon` | partial overlap only (`core/get-site-info`, `core/get-environment-info` cover fragments; no single core ability returns wpguard's `{core_version, plugins, themes, site_url}` shape) |
| `wp_get_option` | 1 | `wpguard/get-option` | no |
| `wp_get_post_meta` | 1 | `wpguard/get-post-meta` | no |
| `site_list` | 1 | n/a — always local to wpguard, never remote | n/a |
| `wp_mutate_option` | 2 | `wpguard/mutate-option` | no |
| `wp_mutate_post_meta` | 2 | `wpguard/mutate-post-meta` | no |
| `wp_mutate_post_content` | 2 | `wpguard/mutate-post-content` | no |
| `wp_cache_bust` | 2 (unguarded) | `wpguard/cache-bust` | no |
| `wp_eval` | 3 | *(none — never mapped)* | n/a, and never will be |

The "registered by WP core today?" column is the load-bearing one: it's why
§5.5 proposes wpguard ship its own ability-registering companion rather than
assuming the ecosystem will already satisfy these names.

### 5.4 Wiring into the tool layer

Every guarded call already funnels through `require_approved_packet` in
`guard.py` *before* any transport-specific branch runs — the packet check
in `mutate.py` happens above the `if site_config.transport == ...` dispatch,
not inside any transport module. Adding a third branch to that dispatch does
not touch the gate at all; it's structurally the same change as adding
`companion_plugin` alongside `ssh` was. Sketch for `wp_mutate_option` in
`tools/mutate.py` (only the transport dispatch changes; everything above and
below it — etag, `_change_digest`, `require_approved_packet`, snapshot
recording, `packet.log` — is untouched):

```python
    if site_config.transport == "ssh":
        previous_value = ssh_wpcli.run_wp_cli(...).stdout.strip()
    elif site_config.transport == "companion_plugin":
        previous_value = companion_plugin.call(site_config, "get_option", {...})
    else:  # abilities_api
        previous_value = abilities_api.call(site_config, "wp_get_option", {"option_name": option_name})
    ...
    # after require_approved_packet + snapshot, same pattern for the write:
    if site_config.transport == "ssh":
        ssh_wpcli.run_wp_cli(...)
    elif site_config.transport == "companion_plugin":
        companion_plugin.call(site_config, "update_option", {...})
    else:  # abilities_api
        abilities_api.call(site_config, "wp_mutate_option", {"option_name": option_name, "new_value": new_value})
```

Same pattern applies to `wp_get_option`, `wp_get_post_meta`, `wp_recon`,
`wp_mutate_post_meta`, `wp_mutate_post_content`, `wp_cache_bust` in
`recon.py` / `mutate.py`. `wp_eval` gets no new branch — it keeps its
existing hard `ValueError` for any non-`ssh` transport, now reading "site is
registered via companion_plugin or abilities_api, neither of which ever
exposes raw eval."

One file easy to miss: `tools/packets.py`'s `_run_durable_check` /
`_reread_current_value` (used by `packet_close(durable_check_delay_seconds=
...)`) already branches on `site_config.transport` for its `option` /
`post_meta` / `post_content` re-read kinds, and already documents that
`post_content` durable re-read is unsupported (`NotImplementedError`) for
`companion_plugin` because that transport has no read-only content command.
`abilities_api` needs the same third branch here, and the same question:
does `wpguard/mutate-post-content`'s `output_schema` return the full
content back on a plain read, or was it designed only as a write-and-report
verb? If not, durable re-read silently degrades for `abilities_api`-transport
sites exactly as it already does for `companion_plugin`-transport ones —
worth deciding deliberately rather than discovering it later.

A candidate new Tier-1, packet-free tool: `site_discover_abilities(site)`
— thin wrapper over `abilities_api.discover()`, returning which of
`ABILITY_MAP`'s verbs this site currently satisfies. Useful for an operator
or agent to sanity-check a site before relying on it, the same way
`site_list` lets you sanity-check registered sites today.

### 5.5 The "wpguard-abilities" companion package

Given §5.3's mapping table, the realistic near-term path to full verb
coverage is a small wpguard-authored package that does nothing but
`wp_register_ability()` calls for the names in `ABILITY_MAP` — a spiritual
successor to `wp-plugin/wpguard-companion.php`, but:

- speaking a WordPress-core-native registration API instead of a bespoke
  REST route,
- authenticated via WordPress's own Application Passwords instead of a
  wpguard-specific header (optionally *also* supporting a custom
  transport-level `permission_callback` that checks an `X-WPGuard-Key`-style
  header, for operators who want parity with the current model — the MCP
  Adapter's transport-permission hook explicitly supports inspecting the
  raw request, so this is possible without abandoning today's auth idiom),
- distributable as a Composer package or plugin, matching how
  `wordpress/mcp-adapter` itself is distributed,
- and — importantly — **redundant and safely skippable** the moment a site
  already has equivalent abilities registered by something else. Discovery
  (§5.1 `discover()`) means wpguard never needs to know or care whether
  `wpguard/mutate-option` came from wpguard's own package or a third
  party's.

This package would *not* implement any packet/guard/approval logic itself —
same division of responsibility as today's companion plugin, which is a
dumb, whitelisted executor with no concept of wpguard's packets. All
gating stays entirely in the Python server, per §6.

### 5.6 Fallback behavior and a transport-pinning safeguard

When `abilities_fallback_transport` is set and a verb's ability isn't
registered (`AbilityNotRegisteredError`), the natural design is "retry this
one call against the fallback transport." That's fine for Tier-1 reads. For
Tier-2 dry-run/apply pairs it needs one explicit safeguard: **a dry-run and
its matching apply must resolve to the same transport.** wpguard's etag /
`change_digest` scheme (`guard.build_change_digest`) assumes the "current
value" it hashed at dry-run time is comparable to the "current value" it
re-reads at apply time. If a site's registered-abilities set changed between
those two calls (a plugin got deactivated mid-session, say) and fallback
silently switched transports, the two reads could disagree about the value's
representation even when the underlying WordPress data didn't change,
producing a spurious `ConflictError` at best or a false-negative etag match
at worst. Proposed rule: **resolve and pin the transport at dry-run time**
(record it alongside the `change_digest`), and have `apply=True` refuse to
proceed — with a clear error, not a silent re-resolve — if the resolved
transport would now differ. Fallback should apply at the *site-registration
/ discovery* granularity, not be re-decided mid-flight inside a single
guarded operation.

## 6. What stays exactly the same

Explicitly unaffected by this proposal:

- `guard.py` in full: `PacketStore`, `SnapshotStore`, `require_approved_packet`,
  per-target locking, `build_change_digest`, `WPGUARD_BYPASS_GUARD`.
- `tools/packets.py`'s packet lifecycle tools
  (`packet_open`/`packet_approve`/`packet_log`/`packet_close`/`packet_list`).
- `mutate.py`'s dry-run-by-default / etag / optimistic-concurrency shape for
  every Tier-2 tool.
- `GUARDED_TOOLS` in `mutate.py` and whatever test enumerates it
  (`tests/test_guard_enumeration.py` asserts every guarded tool funnels
  `apply=True` through `require_approved_packet` — that assertion continues
  to hold for free, because the gate call site doesn't move).
- `policy.py` in full — token scopes, rate limiting, `TOOL_TIERS`. No
  transport-specific carve-outs.
- The Tier-3 rule: `wp_eval` stays SSH-only, unconditionally. No ability,
  however capable, changes that. This needs to be a hard rule in code, not
  just a convention, exactly as it is today for `companion_plugin`.
- **No new user-facing "call any ability" passthrough tool.** This is worth
  stating as a constraint, not just an omission: exposing something like a
  generic `wp_call_ability(site, ability_name, input)` tool to make the
  transport feel "complete" would reintroduce, at a wider blast radius, the
  exact problem Tier 3 is deliberately walled off to contain — arbitrary
  site-side capability, callable with no packet gate, except now scoped to
  *whatever abilities the site happens to expose*, including ones from
  plugins that have no idea wpguard exists. `abilities_api.call()` must only
  ever be invoked from inside wpguard's own already-guarded, named tool
  functions, the same way `ssh_wpcli` and `companion_plugin` are today —
  never as a tool of its own.

## 7. Open questions and risks

### 7.1 Version skew

The Abilities API (core, ~8 months old as of this doc) is comparatively
stable; the MCP Adapter (pre-1.0, `v0.5.0` as the latest seen during this
research, with documented breaking transport/observability/hook changes
between `v0.3.0` and `v0.5.0`) is not. This is the main argument for §5's
recommendation to integrate against the Abilities API's own REST routes
(`/wp-abilities/v1/...`) rather than the MCP Adapter's MCP-speaking
endpoints: it's one fewer pre-1.0 dependency in the path, and the target
site doesn't need the adapter installed at all, only WP 6.9+ core. The
tradeoff is losing whatever the adapter adds on top (its own tool-naming
conventions, observability hooks, multi-transport story) — none of which
wpguard needs, since wpguard is not trying to be a generic MCP client to
arbitrary WordPress servers, just a caller of a small fixed verb set. If a
future need for adapter-specific features emerges, talking MCP-to-MCP
(wpguard as MCP client to the site's adapter server) is possible without
much new dependency weight — the `mcp` package is already a wpguard
dependency (`pyproject.toml`, `mcp>=1.2.0`) and includes client-side
primitives — but it's a different integration shape than the httpx-based
`call()`/`discover()` sketch in §5.1, and picking it up should be a
deliberate v2 decision, not folded into v1.

Sites on older core (<6.9) or an outdated/incompatible ability schema are
simply not eligible for this transport, the same category of constraint as
"`wp_eval` needs `ssh`" — `site_register` should reject or clearly warn on
an `abilities_api`-transport registration against a site reporting a WP
core version below 6.9 (discoverable via a Tier-1 recon call itself, which
is a nice bootstrapping irony to be aware of, not a blocker).

### 7.2 Abilities the site hasn't registered

Covered architecturally in §5.1/§5.6 (discovery + `AbilityNotRegisteredError`
+ optional pinned fallback). Two things worth flagging explicitly:

- **Discovery itself requires authentication** — `/wp-abilities/v1/abilities`
  is not anonymously readable[^4]. wpguard can't pre-flight "does this site
  support the abilities transport at all" without first having working
  credentials for it, unlike, say, an unauthenticated version probe.
- **Staleness**: a discovered capability map can go stale if the site owner
  deactivates the plugin/package that registered an ability. The failure
  mode should be a clear `AbilityNotRegisteredError` surfaced to the caller
  (or triggering the pinned-fallback path from §5.6), not a confusing
  generic HTTP error. Re-discovery should be cheap enough to re-run
  on-demand (an explicit `site_discover_abilities` call, §5.4) rather than
  only ever cached indefinitely from `site_register` time.

### 7.3 Permission model mismatch (WP capabilities vs. wpguard tiers)

These are two independent authorization systems that don't know about each
other, and routing through `abilities_api` means both apply simultaneously:

1. **wpguard's own scope check** (`policy.py`, `recon`/`mutate`/`admin`
   bearer tokens) — enforced before the tool function runs, unchanged by
   this proposal.
2. **WordPress's own capability checks** — layered, per §3.2: the MCP
   Adapter/transport-level `permission_callback` (if going through the
   adapter) or nothing extra (if calling the Abilities REST API directly,
   where WordPress's normal REST authentication is the only gate before the
   ability's own check runs), *and* the specific ability's
   `permission_callback` (typically `current_user_can('some_capability')`),
   evaluated against whichever WordPress user the Application Password
   belongs to.

These can disagree in either direction, silently:

- A wpguard `mutate`-scope token is, by wpguard's own policy, allowed to
  call `wp_mutate_option`. If the Application Password's WordPress user
  only has `edit_posts` and `wpguard/mutate-option`'s `permission_callback`
  requires `manage_options`, the call fails at the WordPress end — a
  transport-level permission error, not a wpguard policy decision, and
  operators need to understand they're now provisioning least-privilege in
  *two* places that must be kept coherent by hand: wpguard's token scope,
  and the WP user's capabilities.
- Conversely, if that WordPress user actually holds `manage_options` (broad
  WP-side power), WordPress's own ability gate won't stop an overreach —
  wpguard's own token-scope check becomes the *only* thing preventing a
  `recon`-scoped caller from doing more than recon, exactly as it is today,
  but now with an extra, differently-configured credential in the mix that
  could quietly be over-privileged relative to what wpguard's policy layer
  assumes.
- wpguard cannot statically verify these two systems are aligned — it has
  no reliable way to introspect "what can this Application Password's user
  actually do" ahead of attempting a call; misalignment surfaces only as a
  runtime 401/403 from WordPress. The mitigation is operational, not
  technical: document (in the README, alongside the existing companion-
  plugin API-key guidance) that the Application Password should belong to
  a dedicated, minimally-privileged WordPress user whose capabilities are
  deliberately scoped to match — not exceed — what wpguard's own token
  scope for that site is meant to allow.

### 7.4 Other risks

- **No plugin-directory listing (yet).** `wordpress/mcp-adapter` is
  Composer/GitHub-only today[^10]. That's a real adoption-friction data
  point: "no companion plugin to install" for the *adapter* is currently
  true only for developer-comfortable site owners; a one-click
  wordpress.org install is not yet an option. This affects the adapter, not
  the core Abilities API itself (which needs nothing extra on 6.9+), but if
  §5.5's wpguard-abilities companion is itself distributed the same way,
  the "easier to install than the current companion plugin" pitch needs a
  second look — a Composer-only package may be a *higher* bar for a
  non-technical site owner than a zip-and-activate WordPress plugin, even
  if it's a smaller/more standard one for a technically comfortable
  operator.
- **Etag/output-shape portability across transports** — flagged in §5.6:
  a value's etag is only meaningful within one transport's read shape for a
  given call pair; don't assume it's portable if a site's transport
  changes between a dry-run and its apply.
- **`packets.py`'s durable-reread gap** — flagged in §5.4: easy to wire the
  write paths for a new transport and forget `_reread_current_value`,
  silently degrading `packet_close(durable_check_delay_seconds=...)` for
  `abilities_api` sites the same way it's already degraded (by explicit
  design, with a `NotImplementedError`) for `companion_plugin` sites on
  `post_content`.
- **Ability schema drift is not wpguard's to control.** If a third-party
  plugin (not wpguard's own companion) happens to register something whose
  name matches an entry in `ABILITY_MAP` but a different input/output
  shape, `call()` will send/parse the wrong shape. Namespacing wpguard's
  expected ability names under a wpguard-controlled prefix (`wpguard/...`,
  as sketched in §5.1) avoids accidental collisions with unrelated plugins;
  it does not protect against a *deliberately* malicious or buggy plugin
  registering under that same namespace on a site wpguard doesn't fully
  trust. Given wpguard's threat model already treats recon output as
  untrusted content (`recon_safety.py`), this is consistent with — not a
  new departure from — the project's existing posture, but is worth an
  explicit line in any future implementation's docstring.

## 8. Non-goals of this document

- Not a commitment to build this, or on any timeline.
- Not a claim that `transports/abilities_api.py` exists — it doesn't.
- Not a proposal to change Tier-3 (`wp_eval`)'s SSH-only rule.
- Not a proposal to weaken or bypass `require_approved_packet` for any
  tool, tier, or transport.
- Not an endorsement of the MCP Adapter's default-server meta-tool
  indirection as something wpguard itself should replicate for its callers
  — wpguard's own MCP-facing tool surface (`wp_recon`, `wp_mutate_option`,
  etc.) stays exactly as named and shaped as it is today; the Abilities API
  only changes what happens *inside* those tool functions when
  `site_config.transport == "abilities_api"`.

## 9. Suggested phasing, if this is pursued

1. Land `transports/abilities_api.py` with `call()`/`discover()` against a
   hand-registered test ability on a throwaway WP 6.9+ install, no wpguard
   tool wiring yet — prove the REST shape assumptions in §5.1 against a
   real site.
2. Wire Tier-1 read tools only (`wp_get_option`, `wp_get_post_meta`,
   `wp_recon` best-effort) — lower blast radius, no packet-layer
   interaction to get wrong.
3. Add the `abilities_fallback_transport` + transport-pinning safeguard
   (§5.6) before wiring any Tier-2 verb, since that's the piece that
   protects dry-run/apply consistency.
4. Wire Tier-2 verbs, extending `_reread_current_value` in `packets.py` in
   the same change (§5.4) so durable re-verify doesn't silently regress.
5. Only then consider publishing the wpguard-abilities companion package
   (§5.5) — the transport should work against *any* correctly-shaped
   registered ability before wpguard ships one of its own to guarantee
   coverage.

## Sources

- [From Abilities to AI Agents: Introducing the WordPress MCP Adapter](https://developer.wordpress.org/news/2026/02/from-abilities-to-ai-agents-introducing-the-wordpress-mcp-adapter/) — WordPress Developer Blog, Feb 2026
- [WordPress/mcp-adapter](https://github.com/WordPress/mcp-adapter) — adapter repo (architecture, transports, `create_server()` example, versioning)
- [Introducing the WordPress Abilities API](https://developer.wordpress.org/news/2025/11/introducing-the-wordpress-abilities-api/) — WordPress Developer Blog, Nov 2025
- [`wp_register_ability()` function reference](https://developer.wordpress.org/reference/functions/wp_register_ability/) — developer.wordpress.org
- [abilities-api PHP API docs](https://github.com/WordPress/abilities-api/blob/trunk/docs/php-api.md) — `WP_Ability` class, retrieval helpers
- [Abilities API REST endpoints](https://developer.wordpress.org/apis/abilities-api/rest-api-endpoints/) — developer.wordpress.org Common APIs Handbook
- [mcp-adapter transport-permissions guide](https://github.com/WordPress/mcp-adapter/blob/trunk/docs/guides/transport-permissions.md) — two-layer permission model, `HttpTransport` request access
- [Abilities API in WordPress 6.9](https://make.wordpress.org/core/2025/11/10/abilities-api-in-wordpress-6-9/) — make.wordpress.org core dev note, core-merge confirmation
- [WordPress/abilities-api](https://github.com/WordPress/abilities-api) — standalone repo, archived Feb 5 2026
- [Automattic/mcp-wordpress-remote](https://github.com/Automattic/mcp-wordpress-remote) — Node.js STDIO↔HTTP bridge, Application Password / OAuth auth
- [Automattic/wordpress-mcp](https://github.com/Automattic/wordpress-mcp) — predecessor package, explicitly deprecated in favor of `WordPress/mcp-adapter`
- [Client-Side Abilities API in WordPress 7.0](https://make.wordpress.org/core/2026/03/24/client-side-abilities-api-in-wordpress-7-0/) — make.wordpress.org, forward-looking context only (not fetched in full; title/date referenced for the timeline in §3.3)

[^1]: make.wordpress.org core dev note, "Abilities API in WordPress 6.9," Nov 10 2025 — confirms core merge as of 6.9.
[^2]: developer.wordpress.org function reference for `wp_register_ability()` — signature, args table, example.
[^3]: `WordPress/abilities-api` `docs/php-api.md` — `WP_Ability` class, category registration, validation-order description.
[^4]: developer.wordpress.org Abilities API REST endpoints page — full route table, auth requirements.
[^5]: From the Feb 2026 MCP Adapter announcement's description of WordPress 6.9's shipped default abilities.
[^6]: `WordPress/abilities-api` GitHub repo, archived-repo notice.
[^7]: make.wordpress.org, "Client-Side Abilities API in WordPress 7.0," Mar 24 2026 (title/date only; not fetched in full for this doc).
[^8]: `developer.wordpress.org` Feb 2026 announcement post — default vs. custom server behavior, `meta.mcp.public`, `create_server()` example, STDIO/HTTP config snippets.
[^9]: `WordPress/mcp-adapter` repo root — architecture components, registration example, transport list, versioning/migration notes.
[^10]: Search-result synthesis over Packagist (`wordpress/mcp-adapter`) and the adapter's own installation docs — Composer-first distribution, not on the wordpress.org plugin directory at time of writing.
[^11]: `Automattic/wordpress-mcp` GitHub repo description text.
[^12]: `Automattic/mcp-wordpress-remote` repo description plus the announcement's HTTP-transport config example — Node proxy, Application Password / OAuth auth.
[^13]: `WordPress/mcp-adapter` `docs/guides/transport-permissions.md` — transport vs. ability permission layering, defaults, `HttpTransport` request access, production guidance.
