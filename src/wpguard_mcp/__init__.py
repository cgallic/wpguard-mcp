"""wpguard-mcp: an MCP server for safely reconning, mutating, and verifying
WordPress sites through a small set of guarded, named command verbs.

See README.md for the full architecture and safety model. In short: named
verbs (dry-run -> packet_open with change digest -> approve -> apply -> verify -> packet_close) are the
front door; raw WP-CLI/PHP eval is a deliberately harder-to-reach Tier 3
escape hatch, gated by the same change-packet guard as everything else.
"""

__version__ = "0.1.0"
