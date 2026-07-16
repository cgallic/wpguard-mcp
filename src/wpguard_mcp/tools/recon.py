"""Tier 1 tools: read-only recon and lookups. No change packet required.

Recon output is content of unknown provenance flowing back into the calling
model, so every value a caller might treat as text is wrapped in an
untrusted-content envelope and scanned for instruction-like phrasing (see
recon_safety and issue #9). Recon stays unguarded -- the envelope is the
mitigation, not a block.
"""
from __future__ import annotations

from ..config import get_site_registry
from ..recon_safety import looks_like_injection, wrap_untrusted
from ..transports import companion_plugin, ssh_wpcli


def wp_recon(site: str) -> dict:
    """Read-only site recon: WP core version, active plugins, active theme, site URL.

    Tier 1 -- safe to call at any time, no change packet required.
    """
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        core_version = ssh_wpcli.run_wp_cli(site_config, ["core", "version"]).stdout.strip()
        plugins = ssh_wpcli.run_wp_cli_json(site_config, ["plugin", "list"])
        themes = ssh_wpcli.run_wp_cli_json(site_config, ["theme", "list"])
        site_url = ssh_wpcli.run_wp_cli(site_config, ["option", "get", "siteurl"]).stdout.strip()
        payload = {
            "site": site,
            "transport": "ssh",
            "core_version": core_version,
            "plugins": plugins,
            "themes": themes,
            "site_url": site_url,
        }
    else:
        result = companion_plugin.call(site_config, "recon")
        payload = {"site": site, "transport": "companion_plugin", **(result or {})}

    # Plugin/theme names and the like come from the site; flag if any of it
    # reads like an injection attempt so the caller can review before acting.
    payload["_wpguard"] = {"injection_flagged": looks_like_injection(payload)}
    return payload


def wp_get_option(site: str, option_name: str) -> dict:
    """Read a single WP option by name. Tier 1 -- no change packet required."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        value = ssh_wpcli.run_wp_cli(site_config, ["option", "get", option_name]).stdout.strip()
    else:
        value = companion_plugin.call(site_config, "get_option", {"option_name": option_name})

    return {"site": site, "option_name": option_name, "value": wrap_untrusted(value, field=option_name)}


def wp_get_post_meta(site: str, post_id: int, meta_key: str) -> dict:
    """Read a single post-meta value. Tier 1 -- no change packet required."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        value = ssh_wpcli.run_wp_cli(
            site_config, ["post", "meta", "get", str(post_id), meta_key]
        ).stdout.strip()
    else:
        value = companion_plugin.call(
            site_config, "get_post_meta", {"post_id": post_id, "meta_key": meta_key}
        )

    return {
        "site": site,
        "post_id": post_id,
        "meta_key": meta_key,
        "value": wrap_untrusted(value, field=f"post:{post_id}:{meta_key}"),
    }


def site_list() -> list[dict]:
    """List all registered sites and their transport (no secrets included). Tier 1."""
    registry = get_site_registry()
    return [site.to_dict() for site in registry.list()]
