"""Packet lifecycle tools (packet_open / packet_log / packet_close) and
site_register -- the tools that set up and account for guarded work,
as opposed to the recon/mutate tools that do the guarded work itself.
"""
from __future__ import annotations

from ..config import SiteConfig, get_site_registry
from ..guard import get_packet_store


def packet_open(site: str, summary: str, risk: str = "low") -> dict:
    """Open a change packet for `site`. Required before any apply=True mutation
    on that site. `risk` is a free-text label (e.g. "low", "medium", "high") --
    wpguard doesn't enforce a fixed enum, but the README recommends staying
    consistent so packet history stays scannable.
    """
    store = get_packet_store()
    packet = store.open_packet(site=site, summary=summary, risk=risk)
    return packet.to_dict()


def packet_log(packet_id: str, message: str) -> dict:
    """Append a log line to an open packet -- e.g. "dry-run previewed", "applied,
    old value captured", "verified via wp_recon". Fails if the packet is closed.
    """
    store = get_packet_store()
    packet = store.log(packet_id, message)
    return packet.to_dict()


def packet_close(packet_id: str, outcome: str = "") -> dict:
    """Close a packet once the change has been applied and verified.
    `outcome` is a free-text summary of the result, e.g. "verified, homepage
    loads, option confirmed via wp_get_option".
    """
    store = get_packet_store()
    packet = store.close_packet(packet_id, outcome=outcome)
    return packet.to_dict()


def packet_list(site: str | None = None, open_only: bool = False) -> list[dict]:
    """List packets, optionally filtered to one site and/or only-open packets."""
    store = get_packet_store()
    return [p.to_dict() for p in store.list_packets(site=site, open_only=open_only)]


def site_register(
    name: str,
    transport: str,
    ssh_host: str | None = None,
    ssh_user: str | None = None,
    ssh_port: int = 22,
    ssh_key_path: str | None = None,
    wp_path: str | None = None,
    plugin_url: str | None = None,
    plugin_api_key_env: str | None = None,
    notes: str = "",
    overwrite: bool = False,
) -> dict:
    """Register a site's connection info into the local site registry.

    For transport="ssh": provide ssh_host (required), ssh_user, ssh_port,
    ssh_key_path, wp_path (the --path wp-cli needs if WP isn't at the SSH
    login's default directory).

    For transport="companion_plugin": provide plugin_url (the site's
    /wp-json/wpguard/v1/exec URL) and plugin_api_key_env (the NAME of an
    environment variable on this machine that holds the plugin's API key --
    never pass the key itself as a tool argument).

    No credentials are ever written to the registry file itself.
    """
    site = SiteConfig(
        name=name,
        transport=transport,
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        ssh_key_path=ssh_key_path,
        wp_path=wp_path,
        plugin_url=plugin_url,
        plugin_api_key_env=plugin_api_key_env,
        notes=notes,
    )
    registry = get_site_registry()
    registered = registry.register(site, overwrite=overwrite)
    return registered.to_dict()
