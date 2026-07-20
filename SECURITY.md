# Security

wpguard-mcp lets AI clients write to live WordPress sites. This document is the
honest answer to "what stops this going wrong" — the trust boundaries, what the
guard does and (importantly) does **not** protect against, the known open
risks, and how to report a vulnerability.

If you only read one thing: **the guard makes it structurally hard to write to
a site by accident. It does not, and cannot, stop a fully-authorized,
deliberately-malicious caller who has been given an admin-scoped token and
approval rights.** Scope your tokens accordingly.

## Trust boundaries

Who can call the server:

- **Anyone holding a valid bearer token.** The server refuses to start without
  at least one token configured and rejects every unauthenticated request
  (401). There is no anonymous/discovery route.
- Tokens are **scoped** (`recon` / `mutate` / `admin`). A token only reaches
  the tier of tools its scope allows; a lower-scoped token calling a
  higher-tier tool gets a `403`, not a silent pass. See "Token scopes" in the
  README.

What a token holder can do, per tier:

| Tier | Scope needed | Blast radius if the token is compromised |
|---|---|---|
| **Tier 1** (recon) | `recon`+ | Read core version, plugins, options, post meta. **Information disclosure** — including any secret ever stored in an option/meta (API keys, tokens). Treat recon output as a full read of the site's config. |
| **Tier 2** (guarded verbs) | `mutate`+ | Write options, post meta, post content; flush cache. Bounded by the change-packet guard: an `apply=True` write needs an *approved* packet. A `mutate` token can both propose and approve, so a compromised `mutate` token can self-authorize Tier 2 writes. |
| **Tier 3** (raw eval) | `admin` | `wp eval` of arbitrary PHP over SSH. **Full site + server compromise** at the WordPress process's privilege level. This is the fire escape, not the front door. |

The takeaway: **`admin` tokens are equivalent to shell access on the target.**
Hand them out like SSH keys, and prefer `recon`/`mutate` tokens for everything
that doesn't genuinely need raw eval.

## What the guard protects against — and what it doesn't

**Protects against:**

- *Unintended* writes. Every mutating tool dry-runs by default (`apply=False`)
  and refuses `apply=True` unless an approved change packet exists for the
  site. A hallucinated or malformed mutation with no packet simply doesn't
  execute.
- *Skipping the gate by drift.* Every Tier 2/3 tool funnels through one shared
  `require_approved_packet` check, and a test enumerates all guarded tools and
  asserts each calls it — so a newly-added tool can't quietly omit the guard.
- *Blind overwrites of changed state.* Optimistic-concurrency etags let an
  apply refuse to clobber a value that changed since the dry-run.
- *Losing the previous value.* Every write snapshots the prior value first.

**Does NOT protect against:**

- *A fully-authorized malicious caller.* If a token has `admin` scope and the
  actor can approve packets, nothing here stops them opening a packet,
  approving it, and running `wp_eval`. The guard raises the bar for accidents
  and creates an audit trail; it is not a sandbox and does not contain a
  determined insider.
- *Prompt injection via recon content.* Recon is unguarded by design (it only
  reads). See "Known open risks" below.
- *Secrets already in the database.* Tier 1 recon can read any option/meta,
  including secrets stored there by other plugins.
- *Anything the WordPress process itself can do.* Tier 3 eval runs as WordPress;
  its blast radius is the WordPress user's privileges on that host.

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
- **Lost-update races** (issue #6, mitigated by etags; opt-in). If a caller
  doesn't pass `expected_etag`, a concurrent editor's change can still be
  overwritten. Per-target locks (issue #3) reduce, but don't eliminate,
  multi-agent races.
- **`WPGUARD_BYPASS_GUARD=1` disables the guard globally.** It exists for local
  throwaway installs only. Never set it against production.

## Deployment guidance

- **Bind to loopback.** The server defaults to `127.0.0.1`. Do not expose the
  port publicly. Reach it from a local MCP client, or over a tunnel / tailnet /
  reverse proxy you control and terminate TLS on.
- **Do not run the guard-bypass in production.** Leave `WPGUARD_BYPASS_GUARD`
  unset.
- **Use least-privilege tokens.** Give each client the lowest scope that works:
  `recon` for read-only harnesses, `mutate` for content ops, `admin` only where
  raw eval is genuinely required.
- **Rotate tokens** periodically and on any suspected compromise. Tokens are
  static shared secrets.
- **Treat companion-plugin site keys as secrets.** The `X-WPGuard-Key` and any
  SSH keys the server uses are credentials to the target site.
- **Keep the state directory private.** `WPGUARD_STATE_DIR` holds the site
  registry (hostnames, paths, usernames) and the audit ledger. It contains no
  passwords, but it's useful recon for an attacker.
- **Consider the notify/cloud hooks' egress.** If you enable
  `WPGUARD_CLOUD_REPORT_URL` or `WPGUARD_NOTIFY_WEBHOOKS`, packet *metadata*
  (site, target, summary, risk, status) leaves the machine to those endpoints.
  Never full content, never credentials. Point them only at endpoints you
  trust.

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.**

Open a private report via **GitHub Security Advisories** — ["Report a
vulnerability"](https://github.com/cgallic/wpguard-mcp/security/advisories/new)
under the repository's *Security* tab. Private vulnerability reporting is
enabled for this repo; this is the only channel we're committing to a
response time on.

Please include a description, reproduction steps, affected version/commit, and
impact. We aim to acknowledge within a few days and will coordinate a fix and
disclosure timeline with you.
