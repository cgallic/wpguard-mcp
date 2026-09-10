# WPGuard product context

Make the change. Keep what matters.

WPGuard is the open-source server behind WP MCP Server. It connects an AI client to WordPress so an operator can inspect a site, preview supported edits, apply a reviewed change, and read the result back. Explicit correction rules preserve requirements on the exact site and field where they belong.

## The useful task

A synthetic example: update a restaurant's reservations page while keeping the “Reserve a table” link pointed at `/reserve`. Record that link requirement with a failing example and a passing example. Later supported edits to that post body are checked against the saved rule. The rule does not automatically extend to other pages.

This is a product example, not a customer story or a recorded demonstration.

## Who it is for

WordPress developers and agency owners who already use an AI client and want it to perform specific maintenance work on sites they control. The practical entry point is one staging site and one content, metadata, or settings change.

## What is available

- Self-hosted, MIT-licensed Core installed from this repository with Python 3.10 or newer, or built from source with Docker Compose.
- WordPress connections through SSH with WP-CLI or the companion plugin.
- An authenticated MCP Streamable HTTP endpoint for compatible clients, including the documented Claude Code, Cursor, Windsurf, and Codex configurations.
- Explicit correction checks on `wp_mutate_post_content`, `wp_mutate_post_meta`, and `wp_mutate_option`.
- Local change records and tool-specific snapshots, plus private import and retrieval of earlier work.

## What the promise does not include

Correction rules require configuration; chat history does not automatically become policy. They do not cover every write path, raw PHP, SQL, file edits, rollback, or edits outside WPGuard. A packet approval is not proof that a separate human reviewed the change. Stored-value checks do not verify layout, interaction, or link health. Recognition of a plugin does not establish a native editing integration. Recovery coverage varies by tool.

The companion key permits administrative operations, including PHP execution and file writes. Token scopes are tool permissions, not tenant isolation. Keep credentials and imported history private.

## Product names and access

Use **WP MCP Server** for the public product and **WPGuard** when introducing the engine or repository. Use **Core** for the free self-hosted server. Cloud is a separate offering with arranged early access; new organizations cannot enroll through an automatic trial or online checkout. Confirm its availability, features, and terms directly. Do not promise a launch date or reservation.

## Primary call to action

[Install from source](https://github.com/cgallic/wpguard-mcp/blob/main/docs/getting-started.md). Connect one staging site, inspect it, and preview one useful change.

Other public references: [product website](https://wpmcpserver.com/), [security boundaries](https://github.com/cgallic/wpguard-mcp/blob/main/SECURITY.md), [client setup](https://github.com/cgallic/wpguard-mcp/blob/main/docs/clients.md), and [Cloud access information](https://wpmcpserver.com/pricing/).

## Publication standard

Use synthetic fixtures for demonstrations and label them in the footage and accompanying text. Report a result only after the actual run supplies it. Do not publish private client histories, identifiable corrections, customer counts, time savings, conversion claims, or customer quotations without their own authorized public source. Launch copy must stay consistent with the README, setup guide, and SECURITY.md at the published commit.
