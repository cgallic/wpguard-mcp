# WP Guard MCP Productization Brief

> This early brief is retained for decision history. The current source of truth is [MASTER-PRODUCT-PLAN-2026-07-16.md](MASTER-PRODUCT-PLAN-2026-07-16.md), which supersedes the early naming and setup-fee pilot recommendations below.

STATUS: active | OWNER: Connor / Codex | NEXT: interview 5 WordPress agencies and close 3 design partners | UPDATED: 2026-07-16 22:00

## Decision

Launch the open-source engine now as `wpguard-mcp`. Do not pretend the cloud control plane is already a self-serve SaaS. Sell a paid, founder-assisted design-partner program while building only the cloud workflow validated by those customers.

Commercial category: **the safety layer for AI changes to client WordPress sites**.

Core promise: **Let AI work on WordPress without giving it an unchecked production shell.**

Best initial buyer: WordPress agencies and technical freelancers managing 10–100 client sites who already use Claude Code, Cursor, Codex, or Windsurf and are nervous about allowing those tools to modify production.

## Brand and Domain

### Final decision — 2026-07-16

Connor acquired **`wpmcp.io`** and **`wpmcpserver.com`**.

- Product/category brand: **WP MCP Server** (short form: **WP MCP**)
- Canonical marketing and SEO domain: **`wpmcpserver.com`**
- Product/application domain: **`wpmcp.io`**
- Open-source engine: **`wpguard-mcp`**
- Paid control plane: **WP MCP Cloud**
- Primary descriptor: **The guarded WordPress MCP server for production sites**
- Differentiated product mechanism: **Change Packets**

Domain architecture:

- `wpmcpserver.com` — canonical public website, landing pages, pricing, comparisons, and search acquisition
- `www.wpmcpserver.com` — permanent redirect to the canonical apex (or the reverse, but choose only one)
- `wpmcp.io` — permanent redirect to `wpmcpserver.com` until the application exists
- `app.wpmcp.io` — paid control plane
- `docs.wpmcp.io` — product and integration documentation
- `api.wpmcp.io` — cloud API when required
- `status.wpmcp.io` — service status

Do not publish duplicate marketing pages on both domains. Use permanent redirects and canonical tags so authority accumulates on `wpmcpserver.com`.

The exact-category `.com` gives the product immediate clarity while using “WP” rather than the protected “WordPress” mark in the brand/domain. The broader PressLatch concept is retired unless a future expansion beyond WordPress creates a real need for a parent-company brand.

### Earlier naming analysis

Keep `wpguard-mcp` as the open-source package/repository name. Use **WP Guard** only as a descriptive engine/project label, not the customer-facing commercial identity.

Reasons:

- An established commercial WordPress firewall/security plugin already uses “WP Guard,” creating category confusion and search competition.
- `wpguard.com`, `wpguard.dev`, `wpguard.ai`, and `wpguard.app` have registry records.
- `usewpguard.com` and `wpguard.io` returned no registry record on 2026-07-16, but domain availability does not solve the name collision.
- The WordPress Foundation explicitly permits “WP” as an alternative in product names, but the stronger problem here is ownability, not trademark compliance.

### Superseded commercial naming shortlist

1. **PressLatch** — strongest recommendation. A memorable safety/gate metaphor; `presslatch.com` returned no registry record.
2. **ChangePacket** — names the product's differentiated primitive; `changepacket.com` returned no registry record. Better if the company may expand beyond WordPress.
3. **GuardedWP** — clearest descriptive option; `guardedwp.com` returned no registry record, but less elegant and still close to generic WP security names.

Registry status is preliminary, not a purchase guarantee. Before buying: check registrar checkout price, USPTO/WIPO marks, GitHub/npm/PyPI handles, and social handles.

These candidates were superseded by the acquisition of `wpmcp.io`.

## Positioning

### One-liner

WP MCP Server is the approval and rollback layer for AI agents changing client WordPress sites.

### Homepage hero

**Let AI fix WordPress. Keep a human on the publish button.**

Your agents can inspect, propose, preview, and verify changes across client sites. Production writes require an approved change packet, with a snapshot and audit trail built in.

Primary CTA: **Join the agency pilot**

Secondary CTA: **Install the open-source MCP**

### Differentiation

Do not sell “another WordPress MCP server.” The official ecosystem and hosting vendors will commoditize connectivity. Sell the control boundary:

- Named, typed operations are the default.
- Raw PHP is a separately scoped break-glass path, not the front door.
- Every write begins as a dry run.
- A specific change packet is proposed and approved before mutation.
- Previous state is captured before the write.
- The result is read back and can be re-verified after delay.
- The paid layer aggregates approvals and audit across a client fleet without holding site credentials.

## Market Evidence

DataForSEO, United States / English, pulled 2026-07-16:

| Query | Estimated monthly search volume | CPC | Competition |
|---|---:|---:|---:|
| wordpress mcp | 720 | $14.45 | 0.12 |
| wordpress mcp server | 210 | $9.49 | 0.17 |
| wordpress mcp plugin | 110 | $6.27 | 0.21 |
| wordpress mcp adapter | 90 | $11.97 | 0.10 |
| claude wordpress mcp | 40 | $33.74 | 0.16 |
| wordpress ai agent | 40 | $11.77 | 0.67 |
| ai agent for wordpress | 30 | $11.04 | 0.47 |

Interpretation:

- This is a real, emerging, high-value niche, not a large horizontal search market.
- “WordPress MCP” should be the acquisition keyword and README/H1 descriptor, not necessarily the company name.
- High CPCs suggest commercial/developer value, but the volume is too small to make SEO the only acquisition motion.
- Agency founder outreach, directory listings, comparison content, GitHub distribution, and ecosystem partnerships should lead; SEO captures existing demand.

Current search results are led by Automattic/WordPress developer resources, GitHub, WPEngine, InstaWP, BionicWP, Reddit, and MCP directories. The winning content wedge is not “what is WordPress MCP?” It is **how to operate WordPress MCP safely in production**.

## Competitive Frame

| Competitor | Their center of gravity | Our viable wedge |
|---|---|---|
| Official WordPress MCP Adapter | Standard abilities/connectivity | Approval, snapshots, verification, fleet governance |
| InstaWP / InstaMCP | Hosting, staging, test-and-promote | Host-neutral, local credentials, explicit per-change authorization |
| Aura | Broad WordPress agency operating system | Narrower safety layer, open engine, no cloud-held site credentials |
| miniOrange | Enterprise policy enforcement from $249/mo | Developer-first, open source, agency-accessible pricing |
| WPVibe and plugin MCPs | Easy in-dashboard connectivity | Closed-by-default production mutation model |

Aura is the closest strategic competitor and is already priced at $29/5 sites, $99/25 sites, and $249/100 sites. Do not copy its “agency operating system” scope. Own the narrower, credible safety layer.

## Offer and Pricing

### Superseded design-partner offer

The earlier **$500 setup + $149/month** pilot concept is retired. It is a service engagement, not the desired self-serve SaaS model.

- Up to 25 sites
- Founder-assisted deployment of the self-hosted MCP
- Slack/Discord approval notifications
- Weekly review of attempted and completed changes
- Direct roadmap access
- Cloud approval dashboard included as it becomes available
- 90-day pilot; cancel anytime

Current founding offer: 50% off normal self-serve pricing for 12 months, onboarding included, with no setup fee.

### Current self-serve pricing hypothesis

| Plan | Price | Limits / buyer |
|---|---:|---|
| Community | $0 | Unlimited local sites; no Cloud |
| Solo Cloud | $19/mo | 5 sites, 1 seat, 30-day Cloud history |
| Agency | $79/mo | 25 sites, 5 seats, one-year evidence retention |
| Agency Pro | $199/mo | 100 sites, 15 seats, routing and three-year retention |
| Platform | $499/mo | 500 sites, 30 seats, advanced fleet controls |

Use a 14-day trial and two months free on annual billing. Do not charge per packet, add setup fees, or offer lifetime plans.

## Minimum Sellable Product

The open-source core is technically credible today: 96 tests pass, Ruff passes, and mypy reports no issues across 16 source files.

Before public launch:

1. Reconcile GitHub issues with reality. Multiple open issues describe features already documented/implemented; close them with evidence or correct the README.
2. Cut a tagged `v0.1.0` release with companion-plugin ZIP, checksums, Docker image, and tested install instructions.
3. Fix mojibake/encoding visible in the local README output and verify GitHub rendering.
4. Publish a 3-minute proof video: recon → propose → approve → dry run → apply → verify → audit.
5. Add a threat-model summary and explicit “what this does not protect against” above the fold.
6. Add a design-partner CTA and contact path to the repo.

Paid cloud MVP, in order:

1. Org + instance pairing
2. Signed/idempotent event ingestion
3. Pending approval view and approve/reject action
4. Fleet audit timeline
5. Basic roles: admin, approver, viewer
6. Stripe only after a pilot customer is actively using the workflow

Defer SSO, white-labeling, broad monitoring, provider integrations, bulk updates, and full agency-OS features.

## Go-To-Market

### First 30 days

- Recruit 20 agencies/freelancers already posting about Claude/Cursor + WordPress.
- Offer 5 live “AI production safety teardown” calls; convert 3 to paid pilots.
- Launch on GitHub with the workflow video and a comparison page.
- Submit to MCP directories only after the tagged release and client docs are clean.
- Publish three bottom-funnel pages:
  - WordPress MCP server with human approval
  - Safest way to connect Claude Code to WordPress
  - WordPress MCP vs raw PHP execution
- Create one reproducible destructive-prompt demo showing an unsafe server accepting a dangerous action and WP Guard refusing it without approval.

### Success gates

- 3 paid pilots
- 10 production sites connected
- 50 approved change packets completed
- Zero unrecoverable customer incidents
- At least 40% of weekly active pilot sites complete one verified change
- Five customer quotes using language we can reuse in positioning

## Kill / Continue Criteria

Continue building the SaaS if, within 45 days, at least 3 agencies pay and repeatedly approve real production changes.

Narrow or stop if prospects like the idea but will not install it, will not let it touch production, or use it only for read-only recon. Those signals mean the product is a useful open-source security pattern, not yet a standalone SaaS.

## Immediate Decisions Needed

1. Configure `wpmcpserver.com` as the canonical marketing domain and point `wpmcp.io` to it until the app exists.
2. Finalize self-serve SaaS tiers and founding-customer pricing.
3. Pick five agency contacts for the first founder outreach batch.
