"""Tier 2 (guarded named verbs) and Tier 3 (guarded raw escape hatch) tools.

Every tool here shares one shape:

- Dry-run by default (`apply=False`): read the current value, compute what
  *would* change, and return a preview. Never touches the live site.
- `apply=True`: requires an open, site-matching change packet (see guard.py)
  unless WPGUARD_BYPASS_GUARD=1 is set. Captures a "previous value" snapshot
  immediately before writing, so the write is always reversible in principle.
  Then performs the write and logs it onto the packet.

wp_cache_bust is the one Tier 2 exception: it has no persistent content
effect, so it is not guarded and has no apply flag -- it always runs.
"""
from __future__ import annotations

from ..config import get_site_registry
from ..guard import get_packet_store, get_snapshot_store, require_open_packet
from ..transports import companion_plugin, ssh_wpcli


def wp_mutate_option(site: str, option_name: str, new_value: str, apply: bool = False) -> dict:
    """Update a WP option. Tier 2 -- dry-run unless apply=True, requires an
    open change packet for `site` to actually write.
    """
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        previous_value = ssh_wpcli.run_wp_cli(site_config, ["option", "get", option_name]).stdout.strip()
    else:
        previous_value = companion_plugin.call(site_config, "get_option", {"option_name": option_name})

    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "option_name": option_name,
            "previous_value": previous_value,
            "proposed_value": new_value,
        }

    packet = require_open_packet(get_packet_store(), site)
    snapshot = get_snapshot_store().record(
        packet_id=packet.id, site=site, tool="wp_mutate_option", target=option_name, previous_value=previous_value
    )

    if site_config.transport == "ssh":
        ssh_wpcli.run_wp_cli(site_config, ["option", "update", option_name, new_value])
    else:
        companion_plugin.call(site_config, "update_option", {"option_name": option_name, "new_value": new_value})

    get_packet_store().log(packet.id, f"applied wp_mutate_option({option_name}) -- snapshot {snapshot.id}")
    return {
        "site": site,
        "dry_run": False,
        "applied": True,
        "option_name": option_name,
        "previous_value": previous_value,
        "new_value": new_value,
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
    }


def wp_mutate_post_meta(site: str, post_id: int, meta_key: str, new_value: str, apply: bool = False) -> dict:
    """Update a single post's meta value. Tier 2 -- dry-run unless apply=True,
    requires an open change packet for `site` to actually write.
    """
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        previous_value = ssh_wpcli.run_wp_cli(
            site_config, ["post", "meta", "get", str(post_id), meta_key]
        ).stdout.strip()
    else:
        previous_value = companion_plugin.call(
            site_config, "get_post_meta", {"post_id": post_id, "meta_key": meta_key}
        )

    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "post_id": post_id,
            "meta_key": meta_key,
            "previous_value": previous_value,
            "proposed_value": new_value,
        }

    packet = require_open_packet(get_packet_store(), site)
    snapshot = get_snapshot_store().record(
        packet_id=packet.id,
        site=site,
        tool="wp_mutate_post_meta",
        target=f"post:{post_id}:{meta_key}",
        previous_value=previous_value,
    )

    if site_config.transport == "ssh":
        ssh_wpcli.run_wp_cli(site_config, ["post", "meta", "update", str(post_id), meta_key, new_value])
    else:
        companion_plugin.call(
            site_config,
            "update_post_meta",
            {"post_id": post_id, "meta_key": meta_key, "new_value": new_value},
        )

    get_packet_store().log(
        packet.id, f"applied wp_mutate_post_meta(post {post_id}, {meta_key}) -- snapshot {snapshot.id}"
    )
    return {
        "site": site,
        "dry_run": False,
        "applied": True,
        "post_id": post_id,
        "meta_key": meta_key,
        "previous_value": previous_value,
        "new_value": new_value,
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
    }


def wp_mutate_post_content(site: str, post_id: int, search: str, replace: str, apply: bool = False) -> dict:
    """Search/replace within a single post's content. Tier 2 -- dry-run unless
    apply=True, requires an open change packet for `site` to actually write.

    Dry-run returns the number of matches found and does not touch the post.
    """
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        current_content = ssh_wpcli.run_wp_cli(
            site_config, ["post", "get", str(post_id), "--field=content"]
        ).stdout.rstrip("\n")
        match_count = current_content.count(search)
        proposed_content = current_content.replace(search, replace)

        if not apply:
            return {
                "site": site,
                "dry_run": True,
                "applied": False,
                "post_id": post_id,
                "search": search,
                "replace": replace,
                "match_count": match_count,
            }

        packet = require_open_packet(get_packet_store(), site)
        snapshot = get_snapshot_store().record(
            packet_id=packet.id,
            site=site,
            tool="wp_mutate_post_content",
            target=f"post:{post_id}:content",
            previous_value=current_content,
        )
        ssh_wpcli.run_wp_cli(site_config, ["post", "update", str(post_id), f"--post_content={proposed_content}"])
        get_packet_store().log(
            packet.id, f"applied wp_mutate_post_content(post {post_id}, {match_count} matches) -- snapshot {snapshot.id}"
        )
        return {
            "site": site,
            "dry_run": False,
            "applied": True,
            "post_id": post_id,
            "match_count": match_count,
            "packet_id": packet.id,
            "snapshot_id": snapshot.id,
        }

    # companion_plugin transport: the plugin does the read+count+(optional)write
    # server-side so we don't need a separate get-content command in its
    # whitelist. Passing apply=False makes it preview only.
    preview = companion_plugin.call(
        site_config,
        "search_replace_post_content",
        {"post_id": post_id, "search": search, "replace": replace, "apply": False},
    )
    match_count = (preview or {}).get("match_count", 0)

    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "post_id": post_id,
            "search": search,
            "replace": replace,
            "match_count": match_count,
        }

    packet = require_open_packet(get_packet_store(), site)
    snapshot = get_snapshot_store().record(
        packet_id=packet.id,
        site=site,
        tool="wp_mutate_post_content",
        target=f"post:{post_id}:content",
        previous_value=(preview or {}).get("previous_content"),
    )
    result = companion_plugin.call(
        site_config,
        "search_replace_post_content",
        {"post_id": post_id, "search": search, "replace": replace, "apply": True},
    )
    get_packet_store().log(
        packet.id, f"applied wp_mutate_post_content(post {post_id}, {match_count} matches) -- snapshot {snapshot.id}"
    )
    return {
        "site": site,
        "dry_run": False,
        "applied": True,
        "post_id": post_id,
        "match_count": (result or {}).get("match_count", match_count),
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
    }


def wp_cache_bust(site: str) -> dict:
    """Flush the site's object/page cache. Not guarded -- no content change,
    nothing to snapshot, no packet required. Runs immediately.
    """
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        detail = ssh_wpcli.run_wp_cli(site_config, ["cache", "flush"]).stdout.strip()
    else:
        detail = companion_plugin.call(site_config, "cache_flush")

    return {"site": site, "cache_flushed": True, "detail": detail}


def wp_eval(site: str, php_code: str, apply: bool = False) -> dict:
    """Tier 3 escape hatch: run arbitrary PHP via `wp eval` on `site`.

    SSH-only -- the companion plugin has no eval capability by design.
    Dry-run by default; apply=True requires an open change packet for `site`,
    same as every Tier 2 tool. There is no generic way to snapshot "previous
    state" for arbitrary code, so the snapshot recorded here has
    previous_value=None; treat wp_eval changes as manually-verified-only.
    """
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport != "ssh":
        raise ValueError(
            f"wp_eval is SSH-only (Tier 3); site '{site}' is registered via companion_plugin, "
            f"which never exposes raw PHP eval. Register an ssh-transport site to use wp_eval."
        )

    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "php_code": php_code,
            "note": "not executed; call again with apply=True and an open change packet to run",
        }

    packet = require_open_packet(get_packet_store(), site)
    snapshot = get_snapshot_store().record(
        packet_id=packet.id, site=site, tool="wp_eval", target="raw_php_eval", previous_value=None
    )
    result = ssh_wpcli.run_eval(site_config, php_code)
    get_packet_store().log(
        packet.id,
        f"applied wp_eval (raw PHP, Tier 3) -- snapshot {snapshot.id} recorded with no previous-value "
        f"capture; verify manually",
    )
    return {
        "site": site,
        "dry_run": False,
        "applied": True,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
    }
