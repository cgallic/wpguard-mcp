# WPGuard

**Put your AI assistant to work on WordPress. Preview the edit. Keep the corrections that matter.**

WPGuard connects an MCP client to WordPress so it can inspect a site, update content and settings, and return a record of its changes. When you teach it a supported correction, future edits to that exact target are checked before they are applied.

It is the open-source server behind **WP MCP Server**. Run it on your own machine or server and connect your WordPress sites over SSH or the companion plugin.

[Get started](docs/getting-started.md) · [Product website](https://wpmcpserver.com) · [Security](SECURITY.md) · [MIT license](LICENSE)

## Useful work, with something to review

Ask your assistant to:

- Inspect the active theme, plugins, content types, and available fields before changing a page.
- Find a target page and approved reference, compare their complete stored content, and preview a bounded full-page diff.
- Replace a Gutenberg or classic page body while proving named copy survives and refusing to overwrite a later human edit.
- Update one Gutenberg block structurally, then verify the native WordPress revision created by the write.
- Test a page change on a registered staging site and capture desktop/mobile evidence before opening production approval.
- Update one plugin or theme with version pinning, health checks, and automatic restoration after a failed update.
- Preview a content replacement, setting update, or file edit before applying it.
- Preserve an approved text fragment, field value, or link during later edits to the same target.
- Retrieve earlier work for an exact client and show the originating evidence.
- Review a change packet and the snapshots captured by supported mutation tools.

The tools provide the WordPress access and change records. Your MCP client supplies the assistant and its reasoning.

## Teach it once. Check the next edit.

Suppose a restaurant's reservations page must keep the link labeled **Reserve a table** pointing to `/reserve`.

You record that requirement with a rejected example, an accepted example, and its source. WPGuard first proves the check distinguishes those examples. A later content edit that removes the link fails its preview check and is blocked when the assistant tries to apply it.

This synthetic example uses the `wp_correction_record` MCP tool after registering the site:

```python
wp_correction_record(
    site="restaurant-staging",
    target="post:84:content",
    human_correction="Keep the reservations link on this page.",
    source_ref="review:reservation-link-example",
    human_requested_basis="The site owner requested this link in the example review.",
    kind="html_link",
    expected={"href": "/reserve", "text": "Reserve a table"},
    rejected_value="<p>Contact us to book.</p>",
    accepted_value='<p><a href="/reserve">Reserve a table</a></p>',
)
```

The requirement applies to this registered site and this post body. It does not become a rule for every page or another client. Retiring a correction preserves its history and the reason it was retired.

Supported checks cover exact text presence or absence, scalar equality, a value at a JSON Pointer, and an HTML anchor's destination and text. The link check examines HTML structure; it does not prove the destination works or the link is visible in a browser.

## Start from source

Requires Python 3.10 or newer. These commands install this repository; they do not depend on a published package or container image.

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

The server listens at `http://127.0.0.1:8642/mcp`. Connect a client that supports MCP Streamable HTTP and an `Authorization: Bearer <token>` header, using the value of `WPGUARD_TOKEN_ADMIN` from the server's environment.

Then register your site and call `wp_site_context`. Registration stores connection details; it does not import or modify your site's content.

[The setup guide](docs/getting-started.md) includes Windows, Docker builds, both WordPress connections, and a first edit with a reviewable preview.

## What is included

| Work | Tools and behavior |
|---|---|
| Understand the site | `wp_site_context`, `wp_recon`, `wp_schema_recon`, and `wp_design_context` expose inventory and configuration. Plugin recognition does not imply a complete native integration. |
| Finish one page | `wp_page_list`, `wp_page_get`, and `wp_page_compare` resolve the target and reference. `wp_page_replace_content` previews a complete replacement, checks protected copy and corrections, requires the reviewed etag and exact packet, captures a snapshot, then reads the stored result back. `wp_page_render_verify` captures desktop and mobile screenshots with hashes and DOM checks without changing WordPress. |
| Test before production | `wp_page_stage_and_test` previews both registered peers, applies only to the separately approved staging site, captures rendered evidence, and returns a fresh production preview. It never promotes automatically. |
| Edit content and settings | `wp_mutate_post_content`, `wp_mutate_post_meta`, and `wp_mutate_option` preview by default, check applicable corrections, and capture previous values before approved writes. |
| Work with files and blocks | File tools expose reads and edit previews. `wp_mutate_block` selects and patches one parsed Gutenberg block under the same digest, ETag, correction, snapshot, and packet controls. Post creation defaults to draft. |
| Update components | `wp_vulnerability_scan` returns cached `clean`, `vulnerable`, or `unknown` findings. SSH sites can preview and apply exact plugin/theme updates with post-update health checks and automatic prior-version restoration on failure. |
| Recover content | List and inspect native WordPress revisions, or preview and approve `wp_revert_to_revision`. WPGuard verifies the resulting revision by its complete content hash. |
| Run unattended work | Admins can create narrow preapproval policies bound to a site, source, exact verbs, target pattern, and maximum risk. A matching run receives one exact packet; unmatched work remains blocked. |
| Remember corrections | Record, list, and retire exact-target checks. Failed or unevaluable applicable checks block the three mutation tools above. |
| Consult previous work | Import packet CSVs or correction-episode JSONL and retrieve their source records without turning imported prose into executable instructions. |
| Review changes | Change packets record proposals, approvals, and outcomes. `wpguard audit` displays the local ledger; supported snapshots can be used with rollback tools. |

The server also exposes advanced PHP, SQL, CLI, snippet, and access tools. Their permissions and side effects differ. They are not covered by the correction checks above.

## Bring your own history

Importing history preserves the original records, hashes, and provenance in the instance's state directory. Repeating an identical import is idempotent; changed records retain their earlier versions.

Packet exports use three CSV schemas:

```text
packets:    id,client_slug,site,status,risk,created_at,summary
status:     client_canonical,total_packets,verified,open,blocked,rolled_back
categories: category,packets,distinct_clients,top_clients
```

```bash
python -m wpguard_mcp.history import \
  --packets packets.csv --status status.csv --categories categories.csv \
  --human-requested-basis "The operator confirmed these categories describe human-requested changes."
```

For richer session histories:

```bash
python -m wpguard_mcp.history import-episodes \
  --episodes episodes.jsonl --lessons lessons.md --coverage coverage.md
```

Each JSONL record needs nonempty `episode_id`, `client`, and `site` strings; additional evidence fields are preserved. `wp_history_episodes(client_slug=...)` matches the original `client` value exactly. Packet queries match the packet export's `client_slug` exactly. No alias mapping is inferred between the two exports.

Imported status and acceptance labels remain historical reports. Recording an active correction is a separate operation that requires examples which fail and pass its check. Caller-supplied acceptance references are recorded as attestations, not independently authenticated approvals.

Imports stay on the instance until queried or otherwise shared by its operator. Queries send the selected records to the connected MCP client. Keep private histories out of public repositories and publishable artifacts.

## Know the boundaries

- **Correction coverage is explicit:** option, post-meta, post-content, full-page, block, and native-revision content writes evaluate applicable target rules. Raw PHP, SQL, file edits, new posts, component updates, and changes made outside WPGuard use different safeguards.
- **Rendered verification is bounded.** `wp_page_render_verify` checks the resolved live page at desktop and mobile sizes for HTTP failures, horizontal overflow, broken rendered images, and optional expected text. It stores hashed screenshots and a JSON receipt under `state/render-evidence/`. It does not judge visual quality or exercise interactions and links.
- **Permissions are not human approval.** A mutate-scoped caller can approve packets. An admin-scoped caller can record or retire corrections. Use your surrounding workflow to decide who may do each.
- **Snapshots are tool-specific.** There is no guarantee that every exposed operation is reversible. Maintain your site's regular backups.
- **The companion plugin has administrative capabilities.** Prefer a WordPress Application Password owned by a dedicated administrator. The legacy shared key remains available for existing installations. Server-side token tiers do not protect callers who contact the plugin directly.
- **Local ledgers assume a single writer.** They are not a shared multi-writer database. A successful replay or test does not establish live production deployment.

The updated companion plugin is required for content correction checks. It returns the source content during preview and checks its digest before applying a content replacement. Older plugin responses cannot satisfy that capability check.

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy
pytest -q
```

CI runs lint, type checks, and tests on Python 3.10–3.12. PHP CLI is needed to run the companion-handler tests; without it those tests skip. All public test examples are synthetic.

WPGuard is MIT-licensed. See [LICENSE](LICENSE).
