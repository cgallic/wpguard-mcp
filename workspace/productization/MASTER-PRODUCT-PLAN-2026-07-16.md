# WP MCP Server — Master Product Plan

STATUS: active strategy | OWNER: Connor | NEXT: ship release-quality OSS core and validate the agency governance workflow with 5 design partners | UPDATED: 2026-07-16

## Executive decision

Build **WP MCP Server** as the production-control layer for agencies using AI agents on client WordPress sites.

Do not compete on “connect your AI to WordPress.” That layer is rapidly commoditizing through the official WordPress MCP Adapter, WPVibe, InstaWP, hosting vendors, and plugin ecosystems. Do not attempt to outrun WPVibe on the number of WordPress actions either; it already has broad content, theme, Elementor, WooCommerce, WP-CLI, checksum, and approval capabilities.

Own this narrower problem:

> **An agency needs to let AI work across client WordPress sites without letting the agent, the person prompting it, or a compromised MCP session unilaterally change production.**

The wedge is not a generic approval button. It is **independent production governance**:

- the requester and approver can be different identities;
- policies determine which actions auto-allow, require approval, or hard-deny;
- the execution engine and credentials remain in the customer environment;
- cloud never holds SSH keys, WordPress application passwords, or companion-plugin secrets;
- every approved change is bound to the exact site, target, intent, preview, and expected pre-change state;
- an approval cannot silently authorize a different payload later;
- pre-change evidence, execution evidence, and post-change verification form one durable record;
- one agency can manage these controls across its entire client fleet.

Category language:

- Search/category: **WordPress MCP server**
- Product category: **AI change control for WordPress**
- Short descriptor: **The guarded WordPress MCP server for production sites**
- Enterprise descriptor: **A policy and approval gateway for AI-operated WordPress fleets**

## Brand and domain architecture

- Brand: **WP MCP Server**
- Short brand: **WP MCP**
- Marketing/SEO canonical: `wpmcpserver.com`
- Application: `app.wpmcp.io`
- Documentation: `docs.wpmcp.io`
- API: `api.wpmcp.io`
- Status: `status.wpmcp.io`
- Open-source package/repository: `wpguard-mcp`
- Paid control plane: **WP MCP Cloud**
- Signature mechanism: **Change Packets**
- Signature mode: **Guarded Mode**

Until the application exists, `wpmcp.io` should permanently redirect to `wpmcpserver.com`. Never publish duplicate marketing content across both roots.

## Market truth

### Demand

DataForSEO US/English results pulled on 2026-07-16:

| Keyword | Monthly volume | CPC | Competition |
|---|---:|---:|---:|
| wordpress mcp | 720 | $14.45 | 0.12 |
| wordpress mcp server | 210 | $9.49 | 0.17 |
| wordpress mcp plugin | 110 | $6.27 | 0.21 |
| wordpress mcp adapter | 90 | $11.97 | 0.10 |
| claude wordpress mcp | 40 | $33.74 | 0.16 |
| wordpress ai agent | 40 | $11.77 | 0.67 |
| ai agent for wordpress | 30 | $11.04 | 0.47 |

This is an emerging, high-intent niche, not a mass-market SEO category. Search demand can support acquisition and authority, but cannot carry the business alone. The initial growth engine must combine GitHub, integration directories, agency communities, ecosystem partnerships, founder-led outreach, and technical proof content.

The live SERP is already controlled by official WordPress/Automattic resources, GitHub, WPEngine, InstaWP, BionicWP, Reddit, YouTube, and MCP directories. Generic educational content such as “What is WordPress MCP?” will be difficult to own. The content wedge is production safety and agency governance.

### Competition is validation

Competition proves four things:

1. WordPress is becoming agent-operable.
2. MCP connectivity is expected to be free or cheap.
3. Customers are already being taught to care about approval, rollback, and audit.
4. A paid governance layer exists between consumer plugins and $249+/month enterprise controls.

### Competitive landscape

| Product | Current center of gravity | Pricing signal | Implication for WP MCP |
|---|---|---|---|
| Official WordPress MCP Adapter | Standard Abilities discovery and execution | Free/open | Never position basic connectivity as the moat. Support/align with Abilities API. |
| WPVibe | Easiest broad MCP connection; extensive WordPress actions; in-chat destructive approvals and audit | Free; Pro $19/mo or $99/yr; Power $49/mo or $299/yr | Do not compete on action breadth or single-user ease. Its approval model makes basic HITL table stakes. |
| InstaWP/InstaMCP | Hosted sites, staging, test-and-promote, MCP bundled with hosting | Hosting from roughly $5/site/month | Win on host neutrality, local credential custody, and governance across mixed hosts. |
| Aura | Broad agency operating system with fleet ops, providers, approvals, rollback, monitoring | $29/5 sites; $99/25; $249/100 | Closest SMB strategic competitor. Stay narrower, deeper, more portable, and security-specific. |
| miniOrange | Enterprise AI policy enforcement, DLP, identities, approvals, audit | Free connection; premium from $249/month | Validates governance willingness to pay. Win below enterprise procurement with agency-first UX. |
| Block MCP | High-quality Gutenberg block edits with revisions | Product-specific | Integrate or emulate block-safe behavior; do not claim generic text replacement is enough. |
| MainWP / WP Umbrella / ManageWP | Traditional fleet maintenance and monitoring | Usually low per-site or extensions | These are substitutes for agency budget, but not direct agent-governance products. Integrations may become channels. |

Primary source references:

- Official WordPress MCP Adapter: https://developer.wordpress.org/news/2026/02/from-abilities-to-ai-agents-introducing-the-wordpress-mcp-adapter/
- WPVibe: https://wordpress.org/plugins/vibe-ai/ and https://mcp.wpvibe.ai/pricing
- Aura: https://my-aura.app/pricing
- miniOrange: https://plugins.miniorange.com/mcp-server-ai-policy-enforcement-wordpress
- InstaWP: https://instawp.com/wordpress-mcp-server/

## Ideal customer profile

### Beachhead ICP

WordPress agencies and technical web-care firms with:

- 10–100 active client sites;
- at least two people who can fill requester and approver roles;
- mixed hosting providers or customer-owned hosting;
- existing use of Claude Code, Cursor, Codex, Windsurf, or automation agents;
- recurring maintenance retainers;
- fear of client-impacting mistakes greater than fear of new tooling;
- enough operational maturity to value audit evidence.

The champion is usually an agency owner, technical director, lead developer, or automation lead. The daily user is a developer/operator. The approver may be a senior developer, account owner, or client stakeholder.

### Secondary ICPs

- Hosting providers wanting a governed agent interface across customer sites.
- Enterprise WordPress teams with change-control requirements but without miniOrange-scale procurement.
- Freelancers managing 5–20 high-value WooCommerce or membership sites.
- Managed-service providers adding AI-assisted WordPress operations.

### Explicit non-ICP

- A blogger connecting one low-risk personal site.
- A nontechnical user primarily seeking AI page generation.
- Agencies that want fully autonomous bulk writes with no review.
- Buyers who require a vendor to hold and operate all site credentials today.
- Enterprise buyers requiring SOC 2, HIPAA, a signed BAA, or formal SLA before purchase.

## Jobs to be done

### Functional jobs

1. Let an AI agent inspect a production WordPress site without exposing secrets or interpreting site content as instructions.
2. Let the agent propose a precise change and produce a human-readable preview.
3. Route risky changes to the right human before execution.
4. Prevent the approved action from changing between preview and execution.
5. Capture enough prior state to reverse or repair the change.
6. Verify that the site retained the intended state after caches, hooks, and plugins run.
7. Prove later who requested, approved, executed, and verified the change.
8. Apply consistent rules across many client sites without centralizing site credentials.

### Emotional jobs

- Give an owner confidence to let the team use AI on production.
- Prevent the “which site did the agent just change?” panic.
- Make clients comfortable with AI-assisted maintenance.
- Let a senior engineer supervise more work without becoming a bottleneck for every harmless read.

### Economic job

Increase the number of client sites each operator can safely maintain while preserving agency margin and reducing incident risk.

## Positioning and messaging

### One-line positioning

**WP MCP Server is the independent approval and evidence layer for AI agents changing client WordPress sites.**

### Hero

**Let AI work on WordPress. Keep production under control.**

Connect Claude, Cursor, Codex, or any MCP client to client sites through guarded operations. Risky writes require an exact approval, capture the previous state, and produce a verifiable audit record—without sending your WordPress credentials to our cloud.

Primary CTA: **Install the open-source server**

Secondary CTA: **Start Cloud free**

Agency CTA: **Book an agency safety review**

### Message hierarchy

1. Production control, not AI novelty.
2. Credentials stay local.
3. Requester and approver can be different people.
4. Approvals are bound to exact payloads and pre-change state.
5. One evidence trail across the client fleet.
6. Works with the AI tools the agency already uses.

### Claims to avoid

- “Unbreakable,” “zero risk,” or “AI can never damage your site.”
- Compliance claims not independently verified.
- “Immutable” until the audit ledger is cryptographically tamper-evident and externally anchored.
- “Rollback” for operations where only a snapshot exists but no tested restore action does.
- “Works with every WordPress plugin/page builder” without integration tests.
- “Never sends content to cloud” if cloud approval previews contain content or diffs.

## Product model

### Three layers

#### 1. WP MCP Core — free and open source

The local execution and enforcement engine.

- MCP endpoint and client integrations
- Local site registry
- SSH + WP-CLI transport
- Companion-plugin transport with hard allowlist and no eval
- Scoped tokens: recon, mutate, admin
- Named verbs and dry-run-by-default mutations
- Local change packets and approvals
- Target locks
- optimistic concurrency/ETags
- pre-write snapshots
- verification and delayed re-verification
- local audit CLI
- optional notifications
- optional cloud pairing

The open-source edition must remain genuinely useful. Artificially crippling local safety would destroy trust and distribution.

#### 2. WP MCP Cloud — paid control plane

The collaboration, policy, and evidence product.

- organizations, teams, roles, and site groups
- pairing of self-hosted instances
- approval inbox across all sites
- mobile-friendly approve/reject links
- centralized audit/evidence timeline
- policy templates and policy inheritance
- retention, export, and client reporting
- Slack/email/Discord notifications
- exception handling and time-bound approvals
- fleet risk and drift views
- billing and entitlements

Cloud is not the executor. It authorizes and records; the local core enforces and executes.

#### 3. WP MCP Enterprise/Platform — later

- SAML/OIDC SSO and SCIM
- custom retention and data residency
- audit-log streaming/webhooks
- external KMS/customer-managed keys
- signed policy bundles
- private cloud/on-prem control plane
- SLA and security review support
- hosting-provider fleet licensing

## The signature object: Change Packet v1

A change packet should become a portable, signed unit with:

- packet ID and schema version;
- organization, instance, site, and environment IDs;
- requester identity and agent/client identity;
- tool/verb name;
- exact normalized arguments or their canonical hash;
- target resources;
- risk classification and reason;
- human summary;
- pre-change state hash/ETag;
- sanitized preview/diff;
- requested expiration time;
- policy decision and matched rule;
- approver identity, decision, comment, and timestamp;
- approval signature bound to packet digest;
- execution result and timestamps;
- snapshot references;
- verification result and evidence;
- close outcome;
- append-only event hash chain.

An approval must authorize the packet digest, not merely a packet ID. Any material change to site, target, verb, arguments, preview, or expected pre-state invalidates the approval.

## Secure cloud architecture

### Current gap

The existing cloud-reporting hook is metadata-only and one-way. That is sufficient for notifications and aggregate logs, but not a real remote approval workflow. A reviewer needs an accurate preview, and the local instance needs a secure way to receive the decision.

### MVP architecture

1. Local core generates an instance key pair during cloud pairing.
2. The customer signs in to Cloud and creates a short-lived pairing code.
3. Core exchanges the code for an instance ID and scoped ingestion credential.
4. Core sends signed packet events outbound over HTTPS.
5. For approval previews, the org chooses one data mode:
   - metadata-only: no content leaves the instance; reviewer sees action/target/risk only;
   - encrypted preview: sanitized diff encrypted in transit and at rest with an org-scoped key;
   - future zero-knowledge mode: browser-decryptable preview using a customer-held key.
6. Cloud records approve/reject against the canonical packet digest.
7. Local core polls an outbound command/decision endpoint. No inbound firewall opening is required.
8. Core verifies Cloud's signature, packet digest, site/target, approver role, and expiry.
9. Approval changes packet state locally. It does not itself execute the mutation.
10. The agent retries the exact apply call; the local guard validates digest and current ETag before writing.
11. Core sends execution and verification events back to Cloud.

### Security boundaries

Cloud may hold:

- account/team identity;
- site aliases and non-secret metadata;
- packet metadata and policy decisions;
- optional sanitized/encrypted previews;
- audit/evidence events;
- public instance keys.

Cloud must not hold:

- SSH private keys;
- WordPress application passwords;
- companion-plugin API keys;
- raw environment variables;
- unrestricted PHP payloads by default;
- reusable local MCP bearer tokens.

## Product features by phase

### Phase 0 — release credibility (0–2 weeks)

- Reconcile open GitHub issues with implemented code.
- Tag `v0.1.0`.
- Publish Docker image and companion-plugin release ZIP with checksums.
- Verify clean installs on Linux, macOS, and Windows/WSL.
- Fix any README encoding/mojibake.
- Add a 3-minute guarded-change demo.
- Publish threat model and security limitations prominently.
- Add GitHub issue templates and vulnerability reporting.
- Add anonymous opt-in install/version telemetry only if privacy language is explicit; otherwise skip.

Exit gate: an unfamiliar developer can connect one test site and complete recon → proposal → approval → dry run → apply → verify in under 15 minutes.

### Phase 1 — core safety completeness (2–6 weeks)

Prioritize high-value, dangerous agency operations—not generic breadth.

- Plugin/theme update with health check and tested automatic rollback.
- Gutenberg block-aware update with native revision reference.
- Snapshot restore/revert tools, not snapshot-only claims.
- Post/page status changes and publishing with exact previews.
- User/role/capability changes with lockout prevention.
- Serialized-data-safe search/replace with mandatory dry run.
- Site health and checksum recon.
- Official WordPress Abilities API adapter for WordPress 6.9+.
- Policy rules in local YAML/JSON: allow, require approval, deny.
- Agent identity separate from bearer-token scope.
- Packet digest/signature format.
- Integration tests against disposable real WordPress containers.

Exit gate: five design partners complete 50 real production change packets with no unrecoverable incident.

### Phase 2 — Cloud MVP (4–10 weeks, overlapping)

- Authentication and organizations.
- Instance pairing and revocation.
- Site inventory and grouping.
- Signed/idempotent event ingestion.
- Pending approval inbox.
- Approve/reject with comments and expiry.
- Outbound local decision polling.
- Event/evidence timeline.
- Admin, approver, and viewer roles.
- Email and Slack notifications.
- 14-day Agency trial and Stripe subscriptions.
- Data export and org deletion.
- Basic status/health page.

Exit gate: at least three paying agencies use Cloud weekly and 40%+ of connected active sites complete a verified change monthly.

### Phase 3 — defensibility (10–20 weeks)

- Policy templates: content, maintenance, WooCommerce, user/security.
- Inheritance: org → site group → site → exception.
- Approval routing by risk, site/client, schedule, or action type.
- Two-person approval for critical actions.
- Time windows and maintenance windows.
- Tamper-evident hash-chained event ledger.
- Signed PDF/JSON client change reports.
- Drift and failed-verification alerts.
- Client portal/observer links.
- Webhooks to ticketing and incident tools.
- Multiple local instances per organization.
- Staging-before-production workflow.
- Bulk proposals that generate per-site packets rather than one dangerous fleet-wide authorization.

### Phase 4 — platform (after repeatable revenue)

- Policy gateway adapters for official WordPress MCP Adapter and other executors.
- Hosting-provider APIs and fleet provisioning.
- SSO/SCIM.
- Customer-managed encryption keys.
- SIEM/log exports.
- Private control plane.
- Formal security audits and compliance program.

### Explicitly defer

- General AI website builder.
- Hosting WordPress sites.
- Holding customer SSH credentials in Cloud.
- Competing with MainWP on monitoring/maintenance breadth.
- Building a generic MCP security company before winning WordPress.
- Broad provider operations such as DNS/CDN/server control.
- Lifetime deals; they damage recurring economics and create indefinite support obligations.

## Packaging and pricing

### Pricing principles

- Core safety stays free and open source.
- Charge for collaboration, centralized policy, evidence, retention, and scale.
- Price primarily by governed active sites because this maps to agency revenue and value.
- Do not charge per change packet; that discourages the behavior the product wants to increase.
- Include reasonable seats; seat overages can monetize collaboration later.
- Use a 14-day trial, no setup fee, and self-serve checkout.
- Annual billing receives two months free (~16.7%), not 50% discounts.

### Recommended launch pricing

| Plan | Monthly | Annual equivalent | Governed sites | Seats | Audit retention | Best for |
|---|---:|---:|---:|---:|---:|---|
| Community | $0 | $0 | Unlimited local; no Cloud | 1 local operator | Local | Developers and OSS adoption |
| Solo Cloud | $19 | $190/year | 5 | 1 | 30 days | Freelancers |
| Agency | $79 | $790/year | 25 | 5 | 1 year | Core ICP / hero plan |
| Agency Pro | $199 | $1,990/year | 100 | 15 | 3 years | Larger agencies |
| Platform | $499 | $4,990/year | 500 | 30 | 7 years | MSPs and hosts |
| Enterprise | Custom, from $12k/year | Annual contract | Custom | Custom | Custom | SSO, private deployment, SLA |

### Feature packaging

Community:

- all local recon and guarded verbs;
- local policies and packets;
- local snapshots, verification, and audit CLI;
- community support.

Solo Cloud:

- centralized packet history;
- one approver workflow;
- email notifications;
- 30-day Cloud history;
- JSON export.

Agency:

- approval inbox;
- team roles;
- Slack/Discord/email;
- site groups;
- policy templates and inheritance;
- one-year evidence retention;
- client-ready reports;
- standard support.

Agency Pro:

- approval routing;
- multi-approver rules;
- staging-to-production workflows;
- webhooks;
- three-year retention;
- priority support.

Platform:

- 500 sites;
- advanced fleet policies;
- audit streaming;
- client sub-organizations;
- onboarding assistance included without a separate setup fee;
- volume overages.

Enterprise:

- SSO/SCIM;
- custom retention/residency;
- private control plane or dedicated deployment;
- customer-managed keys;
- SLA/security review;
- negotiated support.

### Overage hypothesis

- Solo: $4/additional active site/month, capped before Agency becomes cheaper.
- Agency: $3/additional active site/month.
- Agency Pro: $2/additional active site/month.
- Platform: negotiated blocks near $0.75–$1.25/site/month.

An active site is a paired site that reports or receives a packet event during the billing month. This is fairer than charging for dormant archived clients, but it adds billing complexity. For v1, use configured-site limits; introduce active-site billing only after real usage data proves it is needed.

### Founding offer

Do not add a setup fee. Offer the first 20 agencies:

- 50% off the normal monthly price for 12 months;
- price lock while continuously subscribed;
- direct founder channel;
- onboarding assistance included;
- explicit permission to use anonymized product feedback;
- optional public design-partner logo/quote.

Founding Agency is therefore $39/month, not a consulting engagement.

## Cost model

### Recommended initial stack

- App/marketing: Next.js on Vercel Pro.
- Database: Neon Postgres Launch; one shared multi-tenant database with strict org scoping.
- Authentication: Neon Auth or a self-managed library initially; avoid a separate high fixed auth bill before product-market fit.
- Email: Resend.
- Billing: Stripe Checkout, Customer Portal, and webhooks.
- Error tracking: Sentry free initially, paid only when needed.
- Object storage: only if encrypted preview/evidence attachments require it; use short retention and lifecycle deletion.
- Status: static status page initially; external uptime monitor.

Current public list-price inputs checked 2026-07-16:

- Vercel Pro: $20/month with $20 included usage credit.
- Neon Launch: usage based, typical intermittent 1 GB workload around $15/month; $0.106/CU-hour and $0.35/GB-month.
- Resend free: 3,000 emails/month; Pro: $20/month for 50,000.
- Stripe US cards: 2.9% + $0.30 per successful charge.
- Stripe Billing pay-as-you-go: 0.7% of Billing volume if used.

Sources:

- https://vercel.com/pricing
- https://neon.com/pricing
- https://resend.com/pricing
- https://stripe.com/pricing
- https://stripe.com/billing/pricing

### Fixed monthly cost estimates

| Stage | Customers | Estimated fixed/usage infra | Notes |
|---|---:|---:|---|
| Development | 0 | $20–$50 | Vercel Pro; free/low Neon and Resend |
| Early paid | 10–50 | $50–$125 | DB paid tier, monitoring, low email/storage |
| Growth | 100–500 | $150–$500 | More DB compute, email, logs, backups, object storage |
| Scale | 1,000+ | $500–$2,000+ | Highly usage-dependent; still low relative to revenue if no inference/hosting is included |

The product should not pay for LLM inference. Customers bring their AI client/subscription. Cloud processes metadata, policies, approvals, and evidence, so compute cost per packet should be tiny.

### Variable cost assumptions

- Payments + Billing: approximately 3.6% of revenue plus $0.30 per charge under the cited standard rates.
- Email: effectively near zero within allowances; at paid volume, well under one cent per notification.
- Database/event storage: expected pennies per active site at normal packet volume, unless full diffs or attachments are retained for years.
- Support is the dominant real COGS risk. Productized pairing, diagnostics, and documentation matter more than shaving database pennies.

### Scenario economics

Illustrative mix at 100 customers:

- 50 Solo × $19 = $950
- 35 Agency × $79 = $2,765
- 12 Agency Pro × $199 = $2,388
- 3 Platform × $499 = $1,497
- Total MRR = **$7,600**
- Estimated payment/Billing cost at ~3.6% = **$274** plus transaction fixed fees
- Estimated infrastructure = **$100–$250**
- Infrastructure/payment gross margin before support = roughly **93%–95%**

Illustrative mix at 500 customers with the same proportions:

- MRR ≈ **$38,000**
- Payment/Billing percentage ≈ **$1,368** plus fixed transaction fees
- Infrastructure estimate = **$300–$800**
- Infrastructure/payment gross margin before support remains roughly **94%+**

These are planning estimates, not measured production costs.

### SaaS guardrails

- Target blended ARPA after free users: $65–$90/month.
- Target gross margin including ordinary support: >85%.
- Target monthly logo churn: <3% SMB, <1.5% Agency Pro/Platform.
- Target CAC payback: <9 months.
- Target LTV:CAC: >3:1.
- At $76 ARPA, 94% pre-support gross margin, and 3% monthly churn, simple gross-profit LTV is about $2,381; keep fully loaded CAC below ~$700 and preferably below $400 for self-serve.
- Do not add expensive human onboarding to low tiers.
- Do not introduce lifetime plans.

## Activation and product metrics

### Activation event

The customer is activated only when:

> **A second human approves a real change packet, the local engine applies it to a non-demo site, and verification passes.**

Signup, pairing, recon, or packet creation alone are not activation.

### Funnel

1. Visits `wpmcpserver.com` or GitHub.
2. Installs Core.
3. Connects an MCP client.
4. Registers first site.
5. Completes successful recon.
6. Opens and dry-runs first packet.
7. Pairs Cloud.
8. Invites approver.
9. Approver authorizes packet.
10. Exact change executes.
11. Verification passes.
12. Second site connects.

### North-star metric

**Verified governed production changes per active organization per week.**

Supporting metrics:

- time to first successful recon;
- time to first verified packet;
- percentage of packets auto-allowed / approved / denied / expired;
- approval median latency;
- failed verification rate;
- rollback/revert rate;
- weekly active organizations;
- active governed sites;
- organizations with 2+ active approvers;
- conversion from Core install to Cloud pairing;
- trial-to-paid conversion;
- expansion by site count;
- incidents per 1,000 executed packets.

## Go-to-market plan

### Motion 1 — open-source authority

- Clean `v0.1.0` release.
- High-quality README with exact-match terms.
- Docker, pip, companion-plugin ZIP, checksums.
- Client setup guides for Claude, Cursor, Codex, Windsurf, and ChatGPT if supported.
- MCP directory submissions.
- GitHub topics and release notes.
- Public roadmap and security disclosures.

### Motion 2 — proof content

Create evidence no competitor can easily hand-wave:

1. “What happens when an AI agent tries to alter the wrong WordPress option?”
2. Side-by-side unsafe raw eval vs. guarded change packet.
3. Approval tampering test: change one argument after approval and show refusal.
4. Stale-state test: another operator changes the value after preview and show ETag refusal.
5. Plugin update failure and automatic rollback demo.
6. Client-ready audit report generated from a real change.

High-intent pages:

- `/` — guarded WordPress MCP server
- `/wordpress-mcp-server` — exact category page
- `/claude-wordpress-mcp`
- `/cursor-wordpress-mcp`
- `/codex-wordpress-mcp`
- `/wordpress-mcp-security`
- `/wordpress-mcp-for-agencies`
- `/compare/wpvibe`
- `/compare/wordpress-mcp-adapter`
- `/compare/instawp`
- `/pricing`
- `/security`
- `/open-source`

Do not publish unsupported attack pages. Comparisons must be factual, dated, and sourced.

### Motion 3 — founder-led design partners

Build a list of 50 agencies that publicly mention AI-assisted development or WordPress automation.

Offer a 30-minute **AI production safety review**, not a generic demo:

- map how they currently give AI access;
- identify who can approve production;
- test one harmless dry run;
- show the evidence trail;
- invite them to a 14-day Agency trial;
- offer founding pricing if they complete a real verified change.

First milestone: 20 conversations → 10 trials → 5 activated agencies → 3 paid.

### Motion 4 — partnerships

- WordPress hosting companies lacking their own governed MCP layer.
- MainWP/WP Umbrella consultants and communities.
- WordPress security agencies.
- MCP client directories and marketplaces.
- WP-CLI and WordPress developer educators.
- Agencies selling monthly web-care plans.

### Launch sequence

Week 1–2:

- Release credibility work.
- Landing page and waitlist/trial intent.
- Demo video.
- First 20 outreach prospects.

Week 3–4:

- Five live agency reviews.
- Implement the highest-frequency missing safe verb.
- Publish three proof articles.
- Directory submissions.

Month 2:

- Cloud pairing and approval MVP.
- Five design partners.
- Start founding subscriptions.
- Instrument activation funnel.

Month 3:

- Policy templates and reports.
- First integration partner.
- Public launch only after real production evidence and customer quotes.

## Sales narrative

Discovery questions:

- Which AI coding tools touch client WordPress sites today?
- Does the agent get SSH, WP-CLI, application-password, or admin access?
- Who can authorize a production change?
- Can the person prompting the agent also approve the action?
- How do you know the payload executed is the payload reviewed?
- What evidence do you give a client after an AI-assisted change?
- How quickly could you reverse a settings, content, or plugin update mistake?
- Are sites spread across multiple hosts?

Demo flow:

1. Recon a site with a low-privilege token.
2. Attempt a write without a packet; show hard refusal.
3. Open a packet and show exact preview.
4. Have a second person approve in Cloud.
5. Mutate the local state between preview and execution; show stale-state refusal.
6. Re-preview and re-approve.
7. Execute, verify, and show the evidence timeline.

The product is sold in step 5. Most tools can show a green approval button; the differentiator is that approval is exact, independently enforced, and becomes invalid when reality changes.

## Risks and mitigations

### Risk: official WordPress capabilities make our server obsolete

Mitigation: treat the Abilities API as an execution adapter and make governance portable. The long-term product is the control plane and policy boundary, not a proprietary verb catalog.

### Risk: WPVibe wins convenience and feature breadth

Mitigation: integrate with agency workflows and sell separation of duties, cross-site policy, evidence, and local credential custody. Avoid consumer positioning.

### Risk: Aura owns agency fleet messaging

Mitigation: do not become a broad agency OS. Be the neutral safety layer that works across hosts and eventually executors.

### Risk: miniOrange moves downmarket

Mitigation: win developer trust through open source, transparent threat models, easy self-hosting, and predictable self-serve pricing.

### Risk: approval fatigue

Mitigation: policy-based auto-allow for reads and low-risk reversible actions; route only risky actions; allow time-bound, target-bound exceptions; measure approval latency.

### Risk: Cloud becomes a security liability

Mitigation: no site credentials; outbound-only local connection; packet-bound signatures; minimum preview data; encryption; key rotation; tenant isolation; independent security review before enterprise claims.

### Risk: limited action catalog blocks real use

Mitigation: build from observed agency jobs. Do not chase a generic 100-tool catalog. Add the ten dangerous/high-frequency workflows that produce paid usage.

### Risk: support overwhelms margins

Mitigation: one-command install, pairing diagnostics, environment checks, self-serve logs, compatibility matrix, and paid priority support only on higher tiers.

## Validation gates

### 30-day gate

- 20 qualified agency conversations.
- 10 successful local installations.
- 5 agencies complete a real production packet.
- At least 3 agree in writing to pay $79/month or take founding $39/month pricing for Cloud.

### 60-day gate

- 5 paying agencies.
- 50 connected production sites.
- 250 verified packets.
- <2% failed verification excluding deliberately induced tests.
- No unrecoverable incidents.
- At least half of paying orgs use a second approver.

### 90-day gate

- $1,000+ MRR.
- 15 paying organizations.
- 150 connected sites.
- 40%+ weekly active paying organizations.
- 70%+ gross trial retention into month two.
- One repeatable acquisition source producing at least five qualified trials/month.

### Stop or pivot signals

- Agencies consistently refuse to install a local data plane.
- Users only perform read-only recon and will not approve production mutations.
- One-person freelancers dominate and do not value separation of duties.
- Support per new site remains manual after two onboarding iterations.
- Buyers want page generation/action breadth, not governance.

If those occur, pivot toward a developer security library/policy gateway sold to MCP vendors and hosts rather than a direct agency SaaS.

## Immediate execution backlog

### This week

1. Close or update stale GitHub issues with links to implementing commits/tests.
2. Verify README rendering and encoding on GitHub.
3. Define and document Change Packet v1 canonical schema and digest.
4. Draft the Abilities API adapter architecture.
5. Create `v0.1.0` release checklist.
6. Write the landing-page information architecture for `wpmcpserver.com`.
7. Create the first destructive-change refusal demo.
8. Identify 20 design-partner prospects.

### Next engineering sprint

1. Real WordPress Docker integration test harness.
2. Plugin/theme safe update + rollback.
3. Gutenberg block-aware edits + native revision.
4. Cloud pairing key protocol.
5. Signed/idempotent event ingestion.
6. Outbound decision polling.
7. Approval UI bound to packet digest.
8. Stripe trial and entitlement model only after the workflow operates end-to-end.

## Final product thesis

Connectivity will become free. Tool breadth will become expected. A basic approval dialog will become common.

WP MCP Server wins if it becomes the trusted control boundary between an agency's AI agents and its clients' production sites: independent authorization, exact payload binding, local credentials, policy inheritance, and evidence that survives after the chat is gone.

That is narrow enough to launch, valuable enough to charge for, and expandable later into a broader policy gateway without pretending to be that platform today.
