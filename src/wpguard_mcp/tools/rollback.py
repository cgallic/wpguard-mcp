"""1-Click Rollback Engine: restores previous state from the snapshot ledger."""

from __future__ import annotations

import hashlib

from ..config import get_site_registry
from ..guard import ConflictError, get_packet_store, get_snapshot_store, require_approved_packet
from ..transports import companion_plugin, ssh_wpcli


def _target_parts(target: str, expected_kind: str, count: int) -> list[str]:
    parts = target.split(":", count - 1)
    if len(parts) != count or parts[0] != expected_kind or any(not part for part in parts[1:]):
        raise ValueError(f"snapshot target '{target}' is not a valid {expected_kind} target")
    return parts


def _value_from_response(result, field: str):
    return result.get(field) if isinstance(result, dict) and field in result else result


def _sha256(value) -> str:
    return hashlib.sha256(str("" if value is None else value).encode("utf-8")).hexdigest()


def _assert_unchanged(current, expected) -> None:
    actual_digest = _sha256(current)
    expected_digest = _sha256(expected)
    if actual_digest != expected_digest:
        raise ConflictError(
            "value changed after the snapshot write: refusing rollback so newer edits are preserved",
            expected_etag=expected_digest,
            actual_etag=actual_digest,
        )


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

    if snapshot.new_value is None:
        raise ValueError(
            f"snapshot {snapshot_id} has no recorded new_value; safe rollback cannot verify current state"
        )

    packet = require_approved_packet(get_packet_store(), site, target=target)
    registry = get_site_registry()
    site_config = registry.get(site)

    if tool == "wp_mutate_option":
        option_name = _target_parts(target, "option", 2)[1]
        if site_config.transport == "ssh":
            current = ssh_wpcli.run_wp_cli(site_config, ["option", "get", option_name]).stdout.strip()
            _assert_unchanged(current, snapshot.new_value)
            ssh_wpcli.run_wp_cli(site_config, ["option", "update", option_name, str(prev_val or "")])
        else:
            current = _value_from_response(
                companion_plugin.call(site_config, "get_option", {"option_name": option_name}), "value"
            )
            _assert_unchanged(current, snapshot.new_value)
            companion_plugin.call(site_config, "update_option", {
                "option_name": option_name,
                "new_value": prev_val or "",
                "expected_value_sha256": _sha256(snapshot.new_value),
            })
    elif tool == "wp_mutate_post_meta":
        parts = _target_parts(target, "post", 3)
        post_id = int(parts[1])
        meta_key = parts[2]
        if site_config.transport == "ssh":
            current = ssh_wpcli.run_wp_cli(
                site_config, ["post", "meta", "get", str(post_id), meta_key]
            ).stdout.strip()
            _assert_unchanged(current, snapshot.new_value)
            ssh_wpcli.run_wp_cli(site_config, ["post", "meta", "update", str(post_id), meta_key, str(prev_val or "")])
        else:
            current = _value_from_response(
                companion_plugin.call(
                    site_config, "get_post_meta", {"post_id": post_id, "meta_key": meta_key}
                ),
                "value",
            )
            _assert_unchanged(current, snapshot.new_value)
            companion_plugin.call(
                site_config,
                "update_post_meta",
                {
                    "post_id": post_id,
                    "meta_key": meta_key,
                    "new_value": prev_val or "",
                    "expected_value_sha256": _sha256(snapshot.new_value),
                },
            )
    elif tool in ("wp_mutate_post_content", "wp_page_replace_content"):
        parts = _target_parts(target, "post", 3)
        if parts[2] != "content":
            raise ValueError(f"snapshot target '{target}' is not post content")
        post_id = int(parts[1])
        if site_config.transport == "ssh":
            current = ssh_wpcli.run_wp_cli(
                site_config, ["post", "get", str(post_id), "--field=content"]
            ).stdout.rstrip("\n")
            _assert_unchanged(current, snapshot.new_value)
            ssh_wpcli.run_wp_cli(site_config, ["post", "update", str(post_id), f"--post_content={prev_val}"])
        else:
            companion_plugin.call(
                site_config,
                "page_replace_content",
                {
                    "post_id": post_id,
                    "new_content": prev_val or "",
                    "expected_content_sha256": _sha256(snapshot.new_value),
                },
            )
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
