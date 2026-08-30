"""Deep Schema Recon & Database Explorer tools."""
from __future__ import annotations

from ..config import get_site_registry
from ..guard import get_packet_store, require_approved_packet
from ..transports import companion_plugin, ssh_wpcli


def wp_schema_recon(site: str) -> dict:
    """Discover Custom Post Types, Taxonomies, ACF field groups, and active builder plugins."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        import json
        php = (
            "$pts = get_post_types(['public' => true], 'names'); "
            "$taxs = get_taxonomies(['public' => true], 'names'); "
            "$plugins = get_option('active_plugins', []); "
            "$builders = []; "
            "foreach ($plugins as $p) { "
            "  if (stripos($p, 'elementor') !== false) $builders[] = 'Elementor'; "
            "  if (stripos($p, 'bricks') !== false) $builders[] = 'Bricks'; "
            "  if (stripos($p, 'divi') !== false) $builders[] = 'Divi'; "
            "  if (stripos($p, 'oxygen') !== false) $builders[] = 'Oxygen'; "
            "  if (stripos($p, 'woocommerce') !== false) $builders[] = 'WooCommerce'; "
            "  if (stripos($p, 'acf') !== false) $builders[] = 'ACF'; "
            "} "
            "echo json_encode(['post_types' => array_values($pts), 'taxonomies' => array_values($taxs), 'builders' => array_values(array_unique($builders))]);"
        )
        res = ssh_wpcli.run_wp_cli(site_config, ["eval", php])
        return {"site": site, "schema": json.loads(res.stdout.strip())}
    else:
        res = companion_plugin.call(site_config, "schema_recon")
        return {"site": site, "schema": res}


def wp_db_query(site: str, sql_query: str, apply: bool = False) -> dict:
    """Execute a SQL query (safe SELECT read-only, or guarded write query)."""
    registry = get_site_registry()
    site_config = registry.get(site)

    is_select = sql_query.strip().upper().startswith(("SELECT", "SHOW", "DESCRIBE", "EXPLAIN"))

    if not is_select and not apply:
        return {
            "site": site,
            "query": sql_query,
            "dry_run": True,
            "applied": False,
            "note": "Write query requires apply=True and an open change packet.",
        }

    if not is_select:
        packet = require_approved_packet(get_packet_store(), site)

    if site_config.transport == "ssh":
        res = ssh_wpcli.run_wp_cli(site_config, ["db", "query", sql_query])
        if not is_select:
            get_packet_store().log(packet.id, f"applied wp_db_query({sql_query[:50]}...)")
        return {"site": site, "raw_output": res.stdout, "applied": True}
    else:
        res = companion_plugin.call(site_config, "db_query", {"query": sql_query, "apply": apply or is_select})
        if not is_select:
            get_packet_store().log(packet.id, f"applied wp_db_query({sql_query[:50]}...)")
        return {"site": site, "result": res, "applied": True}
