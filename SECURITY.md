# Security

wpguard-mcp can change WordPress sites and execute code. Use staging and trusted
operators. **Token scopes restrict tool access; they do not isolate WordPress or
guarantee human review.** Guard, snapshot, and concurrency coverage varies by tool.

## Private learning sources

Client change histories, session exports, source quotations, and real before/after
examples are private source material. Use them internally to improve the engine;
publish only generalized implementation and synthetic test fixtures. Do not include
the original records or identifiable derivatives in commits, releases, images,
documentation, demonstrations, or sample datasets.

Keep imported history and correction ledgers in `WPGUARD_STATE_DIR`, and private
analysis in `workspace/`. Both are excluded from Git and Docker build contexts.
Known source-export filenames are also excluded when copied elsewhere locally.

## Trust boundaries

Who can call the server:

- **Anyone holding a valid bearer token.** The server refuses to start without
  at least one token configured and rejects every unauthenticated request
  (401). There is no anonymous/discovery route.
- Tokens are **scoped** (`recon` / `mutate` / `admin`). A token only reaches
  the tier of tools its scope allows; a lower-scoped token calling a
  higher-tier tool gets a `403`, not a silent pass. See
  [token configuration](docs/getting-started.md#connect-your-mcp-client).

What a token holder can do, per tier:

| Tier | Scope needed | Blast radius if the token is compromised |
|---|---|---|
| **Tier 1** | `recon`+ | Reads include potentially secret options, metadata, files, and private history. Also includes `wp_magic_login`, which creates an authenticated WordPress login link. This scope is **not strictly read-only**. |
| **Tier 2** | `mutate`+ | Includes content and file writes, SQL, snippets, and `wp_eval_sandbox`. The PHP wrapper catches errors; it does **not** restrict PHP capabilities. Holders can open and approve their own packets. |
| **Tier 3** | `admin` | Adds raw PHP, WP-CLI execution, and correction creation/retirement. Code executes with the configured target account's permissions. |

Treat all current scopes as credentials for trusted operators. In particular,
`mutate` is not a content-only permission, and `recon` is not suitable for an
untrusted observer. Scopes are tool-level, not per-client access controls: a
caller can choose another registered site or history client name.

The companion plugin has a separate trust boundary. Its `X-WPGuard-Key` grants
direct access to the command whitelist, including PHP execution and writes.
Those direct calls do not pass through MCP token scopes, packet approval,
correction checks, or the server snapshot ledger. Keep the key private and
restrict network access to the route. A command whitelist is not code isolation.

## What the guard protects against — and what it doesn't

**Protects against:**

- The three named option, post-meta, and post-content mutation tools preview by
  default and require an approved packet to apply. Supplying the preview's
  change digest binds approval to that proposed change.
- Their applicable correction checks reject failed or unknown results before
  writing. Checks cover exact recorded targets and supported value predicates;
  they do not inspect arbitrary PHP, files, visual output, or every write path.
- These tools record previous values for rollback and accept `expected_etag`
  for changes since preview. Companion content also sends a source digest when
  content is available; applicable content corrections require digest support.
- The guard-enumeration test covers the four tools in `mutate.GUARDED_TOOLS`
  (the three named mutations and raw `wp_eval`), not every registered tool.

**Does NOT protect against:**

- *Self-approval.* A `mutate` or `admin` holder can approve their own packet.
  Approver names and correction acceptance references are caller attestations,
  not independent authentication of a human decision.
- *Universal guarding or rollback.* Cache flushing, snippet toggling, and some
  other operations execute without a preview/packet step. Snapshot coverage
  varies; sandbox PHP has no prior-state snapshot, and raw PHP records a
  placeholder that cannot restore arbitrary side effects. Keep real backups.
- *Prompt injection through returned content.* Envelopes and flags help clients
  distinguish untrusted data; they cannot enforce model behavior.
- *Secrets already in the database.* Tier 1 recon can read any option/meta,
  including secrets stored there by other plugins.
- *Code execution effects.* Both PHP execution tools can exercise the target
  process's permissions, including side effects outside the intended change.

## Known open risks

Tracked openly rather than papered over:

- **Prompt injection through recon output** (issue #9, partially mitigated).
  Tier 1 tools return live site content (option values, post meta) that may
  include attacker-controlled text. wpguard now wraps recon values in an
  `untrusted_content` envelope and flags instruction-like phrasing, but the
  ultimate defense is client-side: **treat all recon output as data, never as
  instructions.**
- **Single-token blast radius before scoping was added** (issue #7, addressed).
  Older deployments using one shared `WPGUARD_MCP_TOKEN` grant admin/Tier 3 to
  every holder. Migrate to scoped tokens.
- **Lost-update races.** `expected_etag` checks are opt-in and do not make
  separate reads and writes atomic. Companion content checks its supplied
  digest server-side, but these checks are not a database transaction spanning
  all editors or all tools.
- **`WPGUARD_BYPASS_GUARD=1` bypasses packet approval.** It does not bypass
  applicable named-mutation correction checks. Keep it unset for real sites.

## Deployment guidance

- **Bind to loopback.** The server defaults to `127.0.0.1`. Do not expose the
  port publicly. Reach it from a local MCP client, or over a tunnel / tailnet /
  reverse proxy you control and terminate TLS on.
- **Do not run the guard-bypass in production.** Leave `WPGUARD_BYPASS_GUARD`
  unset.
- **Use the lowest scope that works**, accounting for the capabilities above.
  For client isolation, run separate instances with separate registries, state,
  and credentials; an exact-client search filter is not an authorization rule.
- **Rotate tokens** periodically and on any suspected compromise. Tokens are
  static shared secrets.
- **Treat companion-plugin site keys as secrets.** The `X-WPGuard-Key` and any
  SSH keys the server uses are credentials to the target site.
- **Keep the state directory private.** It holds snapshots, imported history,
  correction examples, and registry details. Captured option/file values can
  contain passwords or other secrets. Optional Cloud pairing also stores its
  bearer token in `config/cloud.json`. Restrict access and protect backups.
- **Consider the notify/cloud hooks' egress.** If you enable
  `WPGUARD_CLOUD_REPORT_URL` or `WPGUARD_NOTIFY_WEBHOOKS`, packet *metadata*
  (site, target, summary, risk, status) leaves the machine to those endpoints.
  Snapshot content is excluded, but caller-written summaries and other metadata
  are not secret-redacted. Point hooks only at trusted endpoints and keep
  sensitive values out of those fields.

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.**

Open a private report via **GitHub Security Advisories** — ["Report a
vulnerability"](https://github.com/cgallic/wpguard-mcp/security/advisories/new)
under the repository's *Security* tab.

Please include a description, reproduction steps, affected version/commit, and
impact. We aim to acknowledge within a few days and will coordinate a fix and
disclosure timeline with you.
