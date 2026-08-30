"""1-Click Rollback Engine: restores previous state from the snapshot ledger."""
from __future__ import annotations

from ..config import get_site_registry
from ..guard import get_packet_store, get_snapshot_store, require_approved_packet
from ..transports import companion_plugin, ssh_wpcli


def wp_rollback(site: str, snapshot_id: str, apply: bool = False) -> dict:
    """Roll back a previous mutation to its pre-write snapshot state."""
    snapshot = get_snapshot_store().get(snapshot_id)
    if snapshot is None:
        return {"error": f"Snapshot id '{snapshot_id}' not found in ledger"}

    if snapshot.site != site:
        return {"error": f"Snapshot {snapshot_id} belongs to site '{snapshot.site}', not '{site}'"}

    target = snapshot.target
    prev_val = snapshot.previous_value
    tool = snapshot.tool

    if not apply:
        return {
            "site": site,
            "snapshot_id": snapshot_id,
            "dry_run": True,
            "applied": False,
            "tool": tool,
            "target": target,
            "will_restore_value": prev_val,
        }

    packet = require_approved_packet(get_packet_store(), site)
    registry = get_site_registry()
    site_config = registry.get(site)

    if tool == "wp_mutate_option":
        if site_config.transport == "ssh":
            ssh_wpcli.run_wp_cli(site_config, ["option", "update", target, str(prev_val or "")])
        else:
            companion_plugin.call(site_config, "update_option", {"option_name": target, "new_value": prev_val or ""})
    elif tool == "wp_mutate_post_meta":
        parts = target.split(":")
        post_id = int(parts[1])
        meta_key = parts[2]
        if site_config.transport == "ssh":
            ssh_wpcli.run_wp_cli(site_config, ["post", "meta", "update", str(post_id), meta_key, str(prev_val or "")])
        else:
            companion_plugin.call(site_config, "update_post_meta", {"post_id": post_id, "meta_key": meta_key, "new_value": prev_val or ""})
    elif tool == "wp_mutate_post_content":
        parts = target.split(":")
        post_id = int(parts[1])
        if site_config.transport == "ssh":
            ssh_wpcli.run_wp_cli(site_config, ["post", "update", str(post_id), f"--post_content={prev_val}"])
        else:
            companion_plugin.call(site_config, "search_replace_post_content", {"post_id": post_id, "search": "", "replace": prev_val, "apply": True})
    elif tool in ("wp_file_write", "wp_file_edit", "wp_file_delete"):
        path = target.replace("file:", "")
        if site_config.transport == "ssh":
            if prev_val is not None:
                ssh_wpcli.run_ssh_raw(site_config, f"cat << 'EOF' > {path}\n{prev_val}\nEOF")
        else:
            if prev_val is not None:
                companion_plugin.call(site_config, "file_write", {"path": path, "content": prev_val, "apply": True})

    get_packet_store().log(packet.id, f"applied wp_rollback for snapshot {snapshot_id} ({target})")
    return {
        "site": site,
        "snapshot_id": snapshot_id,
        "dry_run": False,
        "applied": True,
        "restored_target": target,
        "packet_id": packet.id,
    }
