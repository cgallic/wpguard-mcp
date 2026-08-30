"""Sandboxed PHP Execution & Snippet Lifecycle Manager tools."""
from __future__ import annotations

from ..config import get_site_registry
from ..guard import get_packet_store, get_snapshot_store, require_approved_packet
from ..transports import companion_plugin, ssh_wpcli


def wp_eval_sandbox(site: str, php_code: str, apply: bool = False) -> dict:
    """Execute PHP in an isolated, error-trapped sandbox wrapper."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "code_preview": php_code[:200] + ("..." if len(php_code) > 200 else ""),
            "length_bytes": len(php_code),
        }

    packet = require_approved_packet(get_packet_store(), site)

    if site_config.transport == "ssh":
        wrapped_code = (
            "ob_start(); $start = microtime(true); $err = null; $res = null; "
            "try { $res = eval(" + repr(php_code) + "); } catch (Throwable $t) { "
            "$err = ['message' => $t->getMessage(), 'line' => $t->getLine()]; } "
            "$out = ob_get_clean(); $dur = round((microtime(true) - $start) * 1000, 2); "
            "echo json_encode(['success' => ($err === null), 'output' => $out, 'error' => $err, 'duration_ms' => $dur]);"
        )
        res = ssh_wpcli.run_wp_cli(site_config, ["eval", wrapped_code])
        import json
        try:
            exec_result = json.loads(res.stdout.strip())
        except Exception:
            exec_result = {"success": True, "output": res.stdout, "duration_ms": 0}
    else:
        exec_result = companion_plugin.call(site_config, "eval_sandbox", {"code": php_code})

    get_packet_store().log(packet.id, f"applied wp_eval_sandbox ({len(php_code)} bytes)")
    return {
        "site": site,
        "dry_run": False,
        "applied": True,
        "packet_id": packet.id,
        "result": exec_result,
    }


def wp_snippet_save(site: str, name: str, code: str, active: bool = True, apply: bool = False) -> dict:
    """Save a managed PHP/CSS code snippet into WordPress."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if not apply:
        return {
            "site": site,
            "dry_run": True,
            "applied": False,
            "name": name,
            "active": active,
            "code_length": len(code),
        }

    packet = require_approved_packet(get_packet_store(), site)

    if site_config.transport == "ssh":
        filename = f"{name}.php" if active else f"{name}.disabled"
        target_path = f"wp-content/mu-plugins/wpguard-snippets/{filename}"
        header = f"<?php\n/**\n * WPGuard Managed Snippet: {name}\n * Status: {'Active' if active else 'Disabled'}\n */\n\n"
        full_content = header + code.strip()
        
        prev_res = ssh_wpcli.run_ssh_raw(site_config, f"cat {target_path} 2>/dev/null || true")
        previous_val = prev_res.stdout if prev_res.stdout else None
        
        snapshot = get_snapshot_store().record(
            packet_id=packet.id, site=site, tool="wp_snippet_save", target=f"snippet:{name}", previous_value=previous_val
        )
        ssh_wpcli.run_ssh_raw(site_config, f"mkdir -p wp-content/mu-plugins/wpguard-snippets && cat << 'EOF' > {target_path}\n{full_content}\nEOF")
        get_packet_store().log(packet.id, f"applied wp_snippet_save({name}) -- snapshot {snapshot.id}")
        return {
            "site": site,
            "dry_run": False,
            "applied": True,
            "name": name,
            "active": active,
            "file": filename,
            "snapshot_id": snapshot.id,
            "packet_id": packet.id,
        }
    else:
        res = companion_plugin.call(
            site_config, "snippet_save", {"name": name, "code": code, "active": active, "apply": True}
        )
        snapshot = get_snapshot_store().record(
            packet_id=packet.id, site=site, tool="wp_snippet_save", target=f"snippet:{name}", previous_value=(res or {}).get("previous_content")
        )
        get_packet_store().log(packet.id, f"applied wp_snippet_save({name}) -- snapshot {snapshot.id}")
        return {
            "site": site,
            "dry_run": False,
            "applied": True,
            "name": name,
            "active": active,
            "snapshot_id": snapshot.id,
            "packet_id": packet.id,
        }


def wp_snippet_toggle(site: str, name: str, active: bool = True) -> dict:
    """Toggle snippet active/disabled state."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        dir_path = "wp-content/mu-plugins/wpguard-snippets"
        if active:
            cmd = f"mv {dir_path}/{name}.disabled {dir_path}/{name}.php 2>/dev/null || true"
        else:
            cmd = f"mv {dir_path}/{name}.php {dir_path}/{name}.disabled 2>/dev/null || true"
        ssh_wpcli.run_ssh_raw(site_config, cmd)
        return {"site": site, "name": name, "active": active, "toggled": True}
    else:
        res = companion_plugin.call(site_config, "snippet_toggle", {"name": name, "active": active})
        return {"site": site, "result": res}


def wp_snippet_list(site: str) -> dict:
    """List all managed snippets installed on the site."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        res = ssh_wpcli.run_ssh_raw(site_config, "ls -la wp-content/mu-plugins/wpguard-snippets/ 2>/dev/null || true")
        return {"site": site, "raw_listing": res.stdout}
    else:
        res = companion_plugin.call(site_config, "snippet_list")
        return {"site": site, "snippets": res}
