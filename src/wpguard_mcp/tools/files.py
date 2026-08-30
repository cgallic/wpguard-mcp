"""Guarded Filesystem Management tools: read, write, edit, tree, and delete."""
from __future__ import annotations

import difflib

from ..config import get_site_registry
from ..guard import get_packet_store, get_snapshot_store, require_approved_packet
from ..transports import companion_plugin, ssh_wpcli


def wp_file_read(site: str, path: str, offset: int = 0, limit: int = 500) -> dict:
    """Read a file under the WordPress directory safely."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        res = ssh_wpcli.run_ssh_raw(site_config, f"cat {path}")
        lines = res.stdout.splitlines(keepends=True)
        total_lines = len(lines)
        slice_lines = lines[offset : offset + limit]
        return {
            "site": site,
            "path": path,
            "total_lines": total_lines,
            "offset": offset,
            "limit": limit,
            "content": "".join(slice_lines),
        }
    else:
        res = companion_plugin.call(site_config, "file_read", {"path": path, "offset": offset, "limit": limit})
        return {"site": site, "file": res}


def wp_file_write(site: str, path: str, content: str, apply: bool = False) -> dict:
    """Write or create a file under WordPress. Dry-run shows diff; apply=True snapshots first."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        prev_res = ssh_wpcli.run_ssh_raw(site_config, f"cat {path} 2>/dev/null || true")
        previous_content = prev_res.stdout if prev_res.returncode == 0 else ""
    else:
        preview = companion_plugin.call(site_config, "file_write", {"path": path, "content": content, "apply": False})
        previous_content = (preview or {}).get("previous_content") or ""

    diff = "".join(
        difflib.unified_diff(
            previous_content.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )

    if not apply:
        return {
            "site": site,
            "path": path,
            "dry_run": True,
            "applied": False,
            "diff": diff,
            "new_size_bytes": len(content),
        }

    packet = require_approved_packet(get_packet_store(), site)
    snapshot = get_snapshot_store().record(
        packet_id=packet.id, site=site, tool="wp_file_write", target=f"file:{path}", previous_value=previous_content
    )

    if site_config.transport == "ssh":
        ssh_wpcli.run_ssh_raw(site_config, f"mkdir -p $(dirname {path}) && cat << 'EOF' > {path}\n{content}\nEOF")
    else:
        companion_plugin.call(site_config, "file_write", {"path": path, "content": content, "apply": True})

    get_packet_store().log(packet.id, f"applied wp_file_write({path}) -- snapshot {snapshot.id}")
    return {
        "site": site,
        "path": path,
        "dry_run": False,
        "applied": True,
        "diff": diff,
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
    }


def wp_file_edit(site: str, path: str, target: str, replacement: str, apply: bool = False) -> dict:
    """Search/replace exact text within a file."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        prev_res = ssh_wpcli.run_ssh_raw(site_config, f"cat {path}")
        current_content = prev_res.stdout
        match_count = current_content.count(target)
        new_content = current_content.replace(target, replacement)

        if not apply:
            return {
                "site": site,
                "path": path,
                "dry_run": True,
                "applied": False,
                "match_count": match_count,
            }

        packet = require_approved_packet(get_packet_store(), site)
        snapshot = get_snapshot_store().record(
            packet_id=packet.id, site=site, tool="wp_file_edit", target=f"file:{path}", previous_value=current_content
        )
        ssh_wpcli.run_ssh_raw(site_config, f"cat << 'EOF' > {path}\n{new_content}\nEOF")
        get_packet_store().log(packet.id, f"applied wp_file_edit({path}, {match_count} matches) -- snapshot {snapshot.id}")
        return {
            "site": site,
            "path": path,
            "dry_run": False,
            "applied": True,
            "match_count": match_count,
            "packet_id": packet.id,
            "snapshot_id": snapshot.id,
        }
    else:
        preview = companion_plugin.call(site_config, "file_edit", {"path": path, "target": target, "replacement": replacement, "apply": False})
        match_count = (preview or {}).get("match_count", 0)

        if not apply:
            return {
                "site": site,
                "path": path,
                "dry_run": True,
                "applied": False,
                "match_count": match_count,
            }

        packet = require_approved_packet(get_packet_store(), site)
        snapshot = get_snapshot_store().record(
            packet_id=packet.id, site=site, tool="wp_file_edit", target=f"file:{path}", previous_value=(preview or {}).get("previous_content")
        )
        companion_plugin.call(site_config, "file_edit", {"path": path, "target": target, "replacement": replacement, "apply": True})
        get_packet_store().log(packet.id, f"applied wp_file_edit({path}, {match_count} matches) -- snapshot {snapshot.id}")
        return {
            "site": site,
            "path": path,
            "dry_run": False,
            "applied": True,
            "match_count": match_count,
            "packet_id": packet.id,
            "snapshot_id": snapshot.id,
        }


def wp_file_tree(site: str, directory: str = "", max_depth: int = 3) -> dict:
    """Explore files and directories within WordPress."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        res = ssh_wpcli.run_ssh_raw(site_config, f"find {directory or '.'} -maxdepth {max_depth} -not -path '*/.*'")
        items = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return {"site": site, "directory": directory, "items": items, "count": len(items)}
    else:
        res = companion_plugin.call(site_config, "file_tree", {"directory": directory, "max_depth": max_depth})
        return {"site": site, "tree": res}


def wp_file_delete(site: str, path: str, apply: bool = False) -> dict:
    """Delete a file with automatic pre-deletion snapshot."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if not apply:
        return {"site": site, "path": path, "dry_run": True, "applied": False}

    packet = require_approved_packet(get_packet_store(), site)

    if site_config.transport == "ssh":
        prev_res = ssh_wpcli.run_ssh_raw(site_config, f"cat {path} 2>/dev/null || true")
        snapshot = get_snapshot_store().record(
            packet_id=packet.id, site=site, tool="wp_file_delete", target=f"file:{path}", previous_value=prev_res.stdout
        )
        ssh_wpcli.run_ssh_raw(site_config, f"rm -rf {path}")
    else:
        preview = companion_plugin.call(site_config, "file_delete", {"path": path, "apply": False})
        snapshot = get_snapshot_store().record(
            packet_id=packet.id, site=site, tool="wp_file_delete", target=f"file:{path}", previous_value=(preview or {}).get("previous_content")
        )
        companion_plugin.call(site_config, "file_delete", {"path": path, "apply": True})

    get_packet_store().log(packet.id, f"applied wp_file_delete({path}) -- snapshot {snapshot.id}")
    return {
        "site": site,
        "path": path,
        "dry_run": False,
        "applied": True,
        "packet_id": packet.id,
        "snapshot_id": snapshot.id,
    }
